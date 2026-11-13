use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use parking_lot::Mutex;
use rand::Rng;
use serde_json::Value;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;

use crate::crawler::api::{build_record, StzyCrawlerApi};
use crate::crawler::client::StzyHttpClient;
use crate::crawler::tags::TagCatalog;
use crate::error::{AppError, AppResult};
use crate::models::{
    AppSettings, CrawlCombo, CrawlFilters, CrawlStats, ResourceRecord, ResourceStatus,
};
use crate::proxy::ProxyPool;
use crate::store::SqliteStore;
use crate::task_engine::download_service::DownloadService;

#[derive(Clone)]
pub struct CrawlRunner {
    pub settings: AppSettings,
    pub filters: CrawlFilters,
    pub store: SqliteStore,
    pub cancel: CancellationToken,
    pub proxy_pool: Arc<ProxyPool>,
    pub client: StzyHttpClient,
    pub api: StzyCrawlerApi,
    pub download_semaphore: Arc<Semaphore>,
    pub convert_semaphore: Arc<Semaphore>,
    pub completed_resource_ids: Arc<HashSet<String>>,
    pub stats: Arc<Mutex<CrawlStats>>,
    on_log: Arc<dyn Fn(String) + Send + Sync>,
    on_record: Arc<dyn Fn(ResourceRecord) + Send + Sync>,
    on_progress: Arc<dyn Fn(CrawlStats) + Send + Sync>,
    on_proxy: Arc<dyn Fn(String) + Send + Sync>,
}

impl CrawlRunner {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        settings: AppSettings,
        filters: CrawlFilters,
        store: SqliteStore,
        cancel: CancellationToken,
        download_semaphore: Arc<Semaphore>,
        convert_semaphore: Arc<Semaphore>,
        completed_resource_ids: HashSet<String>,
        on_log: Arc<dyn Fn(String) + Send + Sync>,
        on_record: Arc<dyn Fn(ResourceRecord) + Send + Sync>,
        on_progress: Arc<dyn Fn(CrawlStats) + Send + Sync>,
        on_proxy: Arc<dyn Fn(String) + Send + Sync>,
    ) -> Self {
        let log_for_proxy = on_log.clone();
        let proxy_pool = ProxyPool::new(settings.clone(), Some(log_for_proxy));
        let client = StzyHttpClient::new(
            settings.clone(),
            store.clone(),
            Some(proxy_pool.clone()),
            Some(cancel.clone()),
            Some(on_proxy.clone()),
        );
        let api = StzyCrawlerApi::new(client.clone());
        Self {
            settings,
            filters,
            store,
            cancel,
            proxy_pool,
            client,
            api,
            download_semaphore,
            convert_semaphore,
            completed_resource_ids: Arc::new(completed_resource_ids),
            stats: Arc::new(Mutex::new(CrawlStats::default())),
            on_log,
            on_record,
            on_progress,
            on_proxy,
        }
    }

    pub fn stop(&self) {
        self.cancel.cancel();
    }

    pub async fn download_workers(&self) -> usize {
        let configured = self.settings.max_download_workers.clamp(1, 32);
        if self.proxy_pool.proxy_mode() == "off" {
            return configured;
        }
        let cap = self.proxy_pool.available_capacity().await;
        let effective_cap = if cap > 0 {
            cap
        } else {
            self.proxy_pool.target_size().max(1)
        };
        configured.min(effective_cap).max(1)
    }

    pub async fn run(&self) -> AppResult<CrawlStats> {
        {
            let mut st = self.stats.lock();
            st.task_mode = "crawl".to_string();
            st.phase = "running".to_string();
            st.outcome.clear();
            st.running = true;
        }
        self.emit_progress();

        let run_res = self.run_inner().await;

        {
            let mut st = self.stats.lock();
            st.running = false;
            st.phase = "finished".to_string();
            if st.paused {
                st.outcome = "paused".to_string();
            } else if st.aborted {
                st.outcome = "failed".to_string();
            } else if st.failed > 0 || st.paid_skipped > 0 || st.preview_limited > 0 {
                st.outcome = "partial".to_string();
            } else {
                st.outcome = "completed".to_string();
            }
        }
        self.emit_progress();

        run_res?;
        let final_stats = self.stats.lock().clone();
        Ok(final_stats)
    }

    async fn run_inner(&self) -> AppResult<()> {
        let catalog = TagCatalog::fetch(&self.client, &self.settings.study_phase_code).await?;
        let combos = catalog.combos(&self.filters)?;
        {
            let mut st = self.stats.lock();
            st.total_combos = combos.len();
        }
        (self.on_log)(format!("已生成 {} 个筛选组合", combos.len()));

        let workers = self.download_workers().await;
        if workers > 1 {
            (self.on_log)(format!(
                "试卷并发数：{workers}，单个试卷内部按页串行处理"
            ));
        }
        if self.proxy_pool.proxy_mode() != "off" {
            let avail = self.proxy_pool.available_capacity().await;
            (self.on_log)(format!(
                "代理严格租约：一个 IP 同时只处理一条下载链路；代理可用 {avail} 个，本轮下载并发上限 {workers}"
            ));
        }
        let account_names = self.client.enabled_account_names();
        if !account_names.is_empty() {
            (self.on_log)(format!("账号轮询顺序：{}", account_names.join(" -> ")));
        }

        let mut consecutive_failures = 0usize;
        let combo_failure_limit = self.settings.combo_failure_limit;
        let scope = &self.settings.task_scope;

        for combo in combos {
            if self.cancel.is_cancelled() {
                self.stats.lock().paused = true;
                (self.on_log)("任务已暂停".to_string());
                break;
            }
            if !scope.is_empty()
                && self
                    .store
                    .is_combo_completed(scope, &combo, &self.settings.subject_code)
                    .unwrap_or(false)
            {
                (self.on_log)("组合曾经跑过，本次继续检查新增或缺失资源".to_string());
            }

            match self.crawl_combo(&combo).await? {
                ComboOutcome::Stopped => {
                    self.stats.lock().paused = true;
                    (self.on_log)("任务已暂停".to_string());
                    break;
                }
                ComboOutcome::Completed => {
                    consecutive_failures = 0;
                    if !scope.is_empty() {
                        let _ = self.store.mark_combo_completed(
                            scope,
                            &combo,
                            &self.settings.subject_code,
                        );
                    }
                    self.stats.lock().completed_combos += 1;
                    self.emit_progress();
                }
                ComboOutcome::Failed => {
                    consecutive_failures += 1;
                    if combo_failure_limit > 0 && consecutive_failures >= combo_failure_limit {
                        let msg = format!(
                            "连续 {consecutive_failures} 个筛选组合失败，已停止任务"
                        );
                        {
                            let mut st = self.stats.lock();
                            st.aborted = true;
                            st.error = msg.clone();
                        }
                        (self.on_log)(msg);
                        break;
                    }
                }
            }
        }
        Ok(())
    }

    pub async fn run_records(&self, records: Vec<ResourceRecord>) -> AppResult<CrawlStats> {
        {
            let mut st = self.stats.lock();
            *st = CrawlStats {
                task_mode: "crawl".to_string(),
                phase: "running".to_string(),
                resources_total: records.len(),
                running: true,
                ..CrawlStats::default()
            };
        }
        self.emit_progress();

        (self.on_log)(format!(
            "继续下载：仅处理未完成资源 {} 份，不重新扫描已完成资源",
            records.len()
        ));
        let workers = self.download_workers().await;
        if workers > 1 {
            (self.on_log)(format!(
                "试卷并发数：{workers}，单个试卷内部按页串行处理"
            ));
        }

        self.handle_resources(records).await;
        if self.cancel.is_cancelled() {
            self.stats.lock().paused = true;
            (self.on_log)("任务已暂停".to_string());
        }

        let mut st = self.stats.lock();
        st.running = false;
        st.phase = "finished".to_string();
        if st.paused {
            st.outcome = "paused".to_string();
        } else if st.failed > 0 || st.paid_skipped > 0 || st.preview_limited > 0 {
            st.outcome = "partial".to_string();
        } else {
            st.outcome = "completed".to_string();
        }
        let snapshot = st.clone();
        drop(st);
        (self.on_progress)(snapshot.clone());
        Ok(snapshot)
    }

    pub async fn estimate(&self) -> AppResult<CrawlStats> {
        let catalog = TagCatalog::fetch(&self.client, &self.settings.study_phase_code).await?;
        let combos = catalog.combos(&self.filters)?;
        let mut stats = CrawlStats {
            task_mode: "estimate".to_string(),
            phase: "running".to_string(),
            total_combos: combos.len(),
            running: true,
            ..CrawlStats::default()
        };
        (self.on_log)(format!("开始预估 {} 个组合", combos.len()));

        for combo in combos {
            if self.cancel.is_cancelled() {
                stats.paused = true;
                break;
            }
            match self.estimate_combo_resources(&combo).await {
                Ok((matched, filtered)) => {
                    stats.resources_seen += matched;
                    stats.resources_total += matched;
                    stats.filtered_skipped += filtered;
                }
                Err(AppError::Cancelled) => {
                    stats.paused = true;
                    break;
                }
                Err(exc) => {
                    stats.failed += 1;
                    (self.on_log)(format!("预估失败：{:?} - {exc}", combo.names()));
                }
            }
            stats.completed_combos += 1;
            (self.on_progress)(stats.clone());
            if self.sleep_jitter(self.settings.list_delay_seconds).await.is_err() {
                stats.paused = true;
                break;
            }
        }

        stats.running = false;
        stats.phase = if stats.paused {
            "finished".to_string()
        } else {
            "preview".to_string()
        };
        stats.outcome = if stats.paused {
            "paused".to_string()
        } else {
            "estimated".to_string()
        };
        (self.on_progress)(stats.clone());
        Ok(stats)
    }

    async fn estimate_combo_resources(&self, combo: &CrawlCombo) -> AppResult<(usize, usize)> {
        let mut page_num = 1usize;
        let mut matched = 0usize;
        let mut filtered = 0usize;
        let mut total_reported = 0usize;

        let max_pages = self
            .filters
            .max_pages_per_combo
            .or(self.settings.max_pages_per_combo)
            .unwrap_or(0);

        while !self.cancel.is_cancelled() {
            if max_pages > 0 && page_num > max_pages {
                break;
            }
            let data = self.list_resources_with_retry(combo, page_num).await?;
            if page_num == 1 {
                total_reported = data
                    .get("total")
                    .and_then(|v| {
                        v.as_u64()
                            .or_else(|| v.as_str().and_then(|s| s.parse::<u64>().ok()))
                    })
                    .unwrap_or(0) as usize;
                if combo.province.code.is_empty() {
                    return Ok((total_reported, 0));
                }
            }
            let items = data
                .get("list")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if items.is_empty() {
                break;
            }
            for item in &items {
                if Self::matches_selected_province(item, combo) {
                    matched += 1;
                } else {
                    filtered += 1;
                }
            }
            let total_page = data
                .get("totalPage")
                .and_then(|v| {
                    v.as_u64()
                        .or_else(|| v.as_str().and_then(|s| s.parse::<u64>().ok()))
                })
                .unwrap_or(0) as usize;
            if page_num >= total_page {
                break;
            }
            page_num += 1;
            self.sleep_jitter(self.settings.list_delay_seconds).await?;
        }

        if filtered > 0 {
            let names = combo.names();
            let prov = names.get("province").cloned().unwrap_or_default();
            (self.on_log)(format!(
                "预估地区过滤：已选 {prov}，过滤 {filtered}/{total_reported} 份"
            ));
        }
        Ok((matched, filtered))
    }

    async fn crawl_combo(&self, combo: &CrawlCombo) -> AppResult<ComboOutcome> {
        let mut page_num = 1usize;
        let names = combo.names();
        let prov_label = names.get("province").cloned().unwrap_or_default();
        (self.on_log)(format!(
            "抓取组合：{} / {} / {} / {} / {} / {}",
            names.get("year").map(String::as_str).unwrap_or(""),
            names.get("scene").map(String::as_str).unwrap_or(""),
            names.get("rank").map(String::as_str).unwrap_or(""),
            prov_label,
            names.get("grade").map(String::as_str).unwrap_or(""),
            names.get("term").map(String::as_str).unwrap_or(""),
        ));

        let max_pages = self
            .filters
            .max_pages_per_combo
            .or(self.settings.max_pages_per_combo)
            .unwrap_or(0);

        while !self.cancel.is_cancelled() {
            if max_pages > 0 && page_num > max_pages {
                return Ok(ComboOutcome::Completed);
            }

            let data = match self.list_resources_with_retry(combo, page_num).await {
                Ok(d) => d,
                Err(AppError::Cancelled) => return Ok(ComboOutcome::Stopped),
                Err(err @ AppError::StzyApi { .. }) => return Err(err),
                Err(exc) => {
                    self.stats.lock().failed += 1;
                    self.emit_progress();
                    (self.on_log)(format!(
                        "组合列表连续失败，跳过当前组合：{prov_label} / 第 {page_num} 页 - {exc}"
                    ));
                    return Ok(ComboOutcome::Failed);
                }
            };

            if page_num == 1 {
                let total = data
                    .get("total")
                    .and_then(|v| {
                        v.as_u64()
                            .or_else(|| v.as_str().and_then(|s| s.parse::<u64>().ok()))
                    })
                    .unwrap_or(0) as usize;
                self.stats.lock().resources_total += total;
                self.emit_progress();
            }

            let items = data
                .get("list")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if items.is_empty() {
                return Ok(ComboOutcome::Completed);
            }

            let mut page_records = Vec::new();
            for item in &items {
                if self.cancel.is_cancelled() {
                    return Ok(ComboOutcome::Stopped);
                }
                if !Self::matches_selected_province(item, combo) {
                    let actual_prov = item
                        .get("provinceName")
                        .and_then(Value::as_str)
                        .unwrap_or("未知地区");
                    let res_name = item
                        .get("resourceName")
                        .or_else(|| item.get("resourceId"))
                        .and_then(Value::as_str)
                        .unwrap_or("");
                    (self.on_log)(format!(
                        "接口返回非目标地区，已过滤：已选 {prov_label}，返回 {actual_prov} - {res_name}"
                    ));
                    self.skip_filtered_resource(res_name);
                    continue;
                }

                let record = build_record(item, combo, &self.settings.subject_name);
                if self.completed_resource_ids.contains(&record.resource_id) {
                    self.skip_completed_resource(&record);
                    continue;
                }
                page_records.push(record);
            }

            self.handle_resources(page_records).await;
            if self.cancel.is_cancelled() {
                return Ok(ComboOutcome::Stopped);
            }

            let total_page = data
                .get("totalPage")
                .and_then(|v| {
                    v.as_u64()
                        .or_else(|| v.as_str().and_then(|s| s.parse::<u64>().ok()))
                })
                .unwrap_or(0) as usize;
            if page_num >= total_page {
                return Ok(ComboOutcome::Completed);
            }
            page_num += 1;
            if self.sleep_jitter(self.settings.list_delay_seconds).await.is_err() {
                return Ok(ComboOutcome::Stopped);
            }
        }
        Ok(ComboOutcome::Stopped)
    }

    async fn list_resources_with_retry(
        &self,
        combo: &CrawlCombo,
        page_num: usize,
    ) -> AppResult<Value> {
        let attempts = self.settings.list_max_retries.max(1);
        let prov = combo.names().get("province").cloned().unwrap_or_default();
        let mut last_err: Option<AppError> = None;

        for attempt in 1..=attempts {
            if self.cancel.is_cancelled() {
                return Err(AppError::Cancelled);
            }
            match self
                .api
                .list_resources(combo, &self.filters, page_num)
                .await
            {
                Ok(data) => return Ok(data),
                Err(AppError::Cancelled) => return Err(AppError::Cancelled),
                Err(err @ AppError::StzyApi { .. }) => {
                    if err.requires_login() {
                        return Err(err);
                    }
                    (self.on_log)(format!(
                        "列表请求失败：{prov} / 第 {page_num} 页（{attempt}/{attempts}）- {err}"
                    ));
                    last_err = Some(err);
                }
                Err(err) => {
                    (self.on_log)(format!(
                        "列表请求失败：{prov} / 第 {page_num} 页（{attempt}/{attempts}）- {err}"
                    ));
                    last_err = Some(err);
                }
            }
            if attempt < attempts {
                self.sleep_jitter(self.settings.list_delay_seconds).await?;
            }
        }
        Err(last_err.unwrap_or_else(|| AppError::Message("列表请求失败".to_string())))
    }

    async fn handle_resources(&self, records: Vec<ResourceRecord>) {
        if records.is_empty() {
            return;
        }
        let workers = self.download_workers().await;
        if workers == 1 || records.len() <= 1 {
            (self.on_log)(format!(
                "本页待下载 {} 份，按顺序处理",
                records.len()
            ));
            for record in records {
                if self.cancel.is_cancelled() {
                    return;
                }
                self.handle_single_resource(record).await;
            }
            return;
        }

        let concurrency = workers.min(records.len());
        (self.on_log)(format!(
            "本页待下载 {} 份，启动 {concurrency} 个下载协程",
            records.len()
        ));
        let page_sem = Arc::new(Semaphore::new(concurrency));
        let mut join_set = JoinSet::new();

        for record in records {
            if self.cancel.is_cancelled() {
                break;
            }
            let runner = self.clone();
            let sem = page_sem.clone();
            join_set.spawn(async move {
                let Ok(_permit) = sem.acquire().await else {
                    return;
                };
                if runner.cancel.is_cancelled() {
                    return;
                }
                runner.handle_single_resource(record).await;
            });
        }

        while join_set.join_next().await.is_some() {
            if self.cancel.is_cancelled() {
                join_set.abort_all();
                break;
            }
        }
    }

    async fn handle_single_resource(&self, mut record: ResourceRecord) {
        if self.cancel.is_cancelled() {
            return;
        }
        {
            let mut st = self.stats.lock();
            st.resources_seen += 1;
            st.current_resource_name = record.resource_name.clone();
        }
        self.emit_progress();

        record.status = ResourceStatus::Downloading;
        record.error.clear();
        (self.on_record)(record.clone());
        (self.on_log)(format!(
            "开始下载：{} - {}",
            record.resource_id, record.resource_name
        ));

        let downloader = self.build_downloader();
        let global_permit = tokio::select! {
            _ = self.cancel.cancelled() => Err(AppError::Cancelled),
            p = self.download_semaphore.acquire() => p.map_err(|_| AppError::Cancelled),
        };

        match global_permit {
            Ok(_permit) => match downloader.handle_resource(&mut record).await {
                Ok(result) => {
                    record.local_dir = result.local_dir;
                    record.image_count = result.saved_pages;
                    record.status = result.status.clone();
                    record.error = result.error;
                    {
                        let mut st = self.stats.lock();
                        st.images_downloaded += result.images_added;
                        st.paid_skipped += result.paid_unavailable;
                        if !matches!(
                            result.status,
                            ResourceStatus::Completed | ResourceStatus::PaidUnavailable
                        ) {
                            st.preview_limited += 1;
                        }
                    }
                }
                Err(AppError::Cancelled) => {
                    record.status = ResourceStatus::Pending;
                    self.stats.lock().paused = true;
                }
                Err(exc) => {
                    record.status = ResourceStatus::Failed;
                    record.error = exc.to_string();
                    self.stats.lock().failed += 1;
                    (self.on_log)(format!("资源失败：{} - {exc}", record.resource_id));
                }
            },
            Err(_) => {
                record.status = ResourceStatus::Pending;
                self.stats.lock().paused = true;
            }
        }

        self.stats.lock().resources_completed += 1;
        (self.on_record)(record.clone());
        if record.status == ResourceStatus::Completed {
            (self.on_log)(format!(
                "下载完成：{} - {}",
                record.resource_id, record.resource_name
            ));
        }
        self.emit_progress();
    }

    fn build_downloader(&self) -> DownloadService {
        let client = StzyHttpClient::new(
            self.settings.clone(),
            self.store.clone(),
            Some(self.proxy_pool.clone()),
            Some(self.cancel.clone()),
            Some(self.on_proxy.clone()),
        );
        let api = StzyCrawlerApi::new(client.clone());
        DownloadService::new(
            self.settings.clone(),
            client,
            api,
            Some(self.convert_semaphore.clone()),
            Some(self.on_log.clone()),
        )
    }

    fn skip_completed_resource(&self, record: &ResourceRecord) {
        {
            let mut st = self.stats.lock();
            st.resources_seen += 1;
            st.resources_completed += 1;
            st.current_resource_name = record.resource_name.clone();
        }
        self.emit_progress();
        (self.on_log)(format!(
            "续跑跳过已完成资源：{} - {}",
            record.resource_id, record.resource_name
        ));
    }

    fn skip_filtered_resource(&self, resource_name: &str) {
        {
            let mut st = self.stats.lock();
            st.resources_seen += 1;
            st.resources_completed += 1;
            st.filtered_skipped += 1;
            st.current_resource_name = resource_name.to_string();
        }
        self.emit_progress();
    }

    fn matches_selected_province(item: &Value, combo: &CrawlCombo) -> bool {
        if combo.province.code.is_empty() {
            return true;
        }
        let actual = item
            .get("provinceName")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        actual == combo.province.name
    }

    fn emit_progress(&self) {
        let snapshot = self.stats.lock().clone();
        (self.on_progress)(snapshot);
    }

    async fn sleep_jitter(&self, base_secs: f64) -> AppResult<()> {
        let jitter: f64 = rand::thread_rng().gen_range(0.0..0.2);
        let delay = base_secs.max(0.0) + jitter;
        if delay <= 0.001 {
            return Ok(());
        }
        tokio::select! {
            _ = self.cancel.cancelled() => Err(AppError::Cancelled),
            _ = tokio::time::sleep(Duration::from_secs_f64(delay)) => Ok(()),
        }
    }
}

enum ComboOutcome {
    Completed,
    Stopped,
    Failed,
}
