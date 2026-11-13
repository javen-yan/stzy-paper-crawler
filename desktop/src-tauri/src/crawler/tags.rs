use std::collections::{BTreeMap, HashSet};

use serde_json::{json, Value};

use crate::crawler::client::StzyHttpClient;
use crate::error::{AppError, AppResult};
use crate::models::{AppSettings, CrawlCombo, CrawlFilters, TagOption};
use crate::store::SqliteStore;

pub const STUDY_PHASES: &[(&str, &str)] = &[("200", "初中"), ("300", "高中")];

#[derive(Debug, Clone)]
pub struct TagCatalog {
    pub tags: BTreeMap<String, Vec<TagOption>>,
}

impl TagCatalog {
    pub async fn fetch(client: &StzyHttpClient, study_phase_code: &str) -> AppResult<Self> {
        let payload = json!({
            "studyPhaseCode": study_phase_code,
            "dictType": "",
            "tagCategory": "1",
        });
        let resp = client
            .post_json(
                "/zw-resource/api/v1/resource/tag/queryQuestionFixedTag",
                &payload,
                None,
                "",
            )
            .await?;
        let groups = resp
            .get("data")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        Ok(Self::from_api(&groups))
    }

    pub fn from_api(groups: &[Value]) -> Self {
        let mut tags: BTreeMap<String, Vec<TagOption>> = BTreeMap::from([
            ("sceneCode".to_string(), Vec::new()),
            ("yearCode".to_string(), Vec::new()),
            ("rank".to_string(), Vec::new()),
            ("provinceCode".to_string(), Vec::new()),
            ("gradeCode".to_string(), Vec::new()),
            ("termCode".to_string(), Vec::new()),
        ]);

        for group in groups {
            let Some(rel_field) = group.get("relField").and_then(Value::as_str) else {
                continue;
            };
            let children = group
                .get("children")
                .and_then(Value::as_array)
                .map(Vec::as_slice)
                .unwrap_or(&[]);
            if rel_field == "area" {
                tags.insert(
                    "provinceCode".to_string(),
                    extract_province_options(children),
                );
            } else if tags.contains_key(rel_field) {
                tags.insert(rel_field.to_string(), extract_options(rel_field, children));
            }
        }
        Self { tags }
    }

    pub fn selected(&self, field: &str, codes: &[String]) -> Vec<TagOption> {
        if codes.is_empty() {
            return vec![TagOption {
                field: field.to_string(),
                code: String::new(),
                name: "不限".to_string(),
            }];
        }
        let wanted: HashSet<&str> = codes.iter().map(String::as_str).collect();
        self.tags
            .get(field)
            .map(|opts| {
                opts.iter()
                    .filter(|o| wanted.contains(o.code.as_str()))
                    .cloned()
                    .collect()
            })
            .unwrap_or_default()
    }

    pub fn validate_filters(&self, filters: &CrawlFilters) -> AppResult<()> {
        let checks: &[(&str, &[String], &str)] = &[
            ("sceneCode", &filters.scenes, "场景"),
            ("yearCode", &filters.years, "年份"),
            ("rank", &filters.ranks, "试卷等级"),
            ("provinceCode", &filters.provinces, "地区"),
            ("gradeCode", &filters.grades, "年级"),
            ("termCode", &filters.terms, "学期"),
        ];
        let mut details = Vec::new();
        for &(field, codes, label) in checks {
            if codes.is_empty() {
                continue;
            }
            let available: HashSet<&str> = self
                .tags
                .get(field)
                .map(|opts| opts.iter().map(|o| o.code.as_str()).collect())
                .unwrap_or_default();
            let missing: Vec<&str> = codes
                .iter()
                .map(String::as_str)
                .filter(|c| !available.contains(c))
                .collect();
            if !missing.is_empty() {
                details.push(format!("{label} {}", missing.join(", ")));
            }
        }
        if !details.is_empty() {
            return Err(AppError::Validation(format!(
                "筛选条件不在当前分类缓存中：{}。请刷新分类后重新选择。",
                details.join("；")
            )));
        }
        Ok(())
    }

    pub fn combos(&self, filters: &CrawlFilters) -> AppResult<Vec<CrawlCombo>> {
        self.validate_filters(filters)?;
        let scenes = self.selected("sceneCode", &filters.scenes);
        let years = self.selected("yearCode", &filters.years);
        let ranks = self.selected("rank", &filters.ranks);
        let provinces = self.selected("provinceCode", &filters.provinces);
        let grades = self.selected("gradeCode", &filters.grades);
        let terms = self.selected("termCode", &filters.terms);

        if scenes.is_empty()
            || years.is_empty()
            || ranks.is_empty()
            || provinces.is_empty()
            || grades.is_empty()
            || terms.is_empty()
        {
            return Ok(Vec::new());
        }

        let mut out = Vec::with_capacity(
            scenes.len()
                * years.len()
                * ranks.len()
                * provinces.len()
                * grades.len()
                * terms.len(),
        );
        for s in &scenes {
            for y in &years {
                for r in &ranks {
                    for p in &provinces {
                        for g in &grades {
                            for t in &terms {
                                out.push(CrawlCombo {
                                    scene: s.clone(),
                                    year: y.clone(),
                                    rank: r.clone(),
                                    province: p.clone(),
                                    grade: g.clone(),
                                    term: t.clone(),
                                });
                            }
                        }
                    }
                }
            }
        }
        Ok(out)
    }
}

fn extract_code(item: &Value, keys: &[&str]) -> String {
    for &k in keys {
        if let Some(val) = item.get(k) {
            let s = match val {
                Value::String(s) => s.trim().to_string(),
                Value::Number(n) => n.to_string(),
                _ => String::new(),
            };
            if !s.is_empty() && s != "0" {
                return s;
            }
        }
    }
    String::new()
}

fn extract_name(item: &Value, keys: &[&str]) -> String {
    for &k in keys {
        if let Some(Value::String(s)) = item.get(k) {
            let trimmed = s.trim();
            if !trimmed.is_empty() {
                return trimmed.to_string();
            }
        }
    }
    String::new()
}

fn extract_options(field: &str, children: &[Value]) -> Vec<TagOption> {
    children
        .iter()
        .filter_map(|item| {
            let code = extract_code(item, &["tagCode", "dictCode", "code"]);
            let name = extract_name(item, &["dictName", "tagName", "name"]);
            if !code.is_empty() && !name.is_empty() {
                Some(TagOption {
                    field: field.to_string(),
                    code,
                    name,
                })
            } else {
                None
            }
        })
        .collect()
}

fn extract_province_options(children: &[Value]) -> Vec<TagOption> {
    children
        .iter()
        .filter_map(|item| {
            let code = extract_code(item, &["tagCode", "code"]);
            let name = extract_name(item, &["dictName", "name"]);
            if !code.is_empty() && !name.is_empty() {
                Some(TagOption {
                    field: "provinceCode".to_string(),
                    code,
                    name,
                })
            } else {
                None
            }
        })
        .collect()
}

pub fn current_catalogs(store: &SqliteStore) -> AppResult<Value> {
    if let Some(cached) = store.get_kv("catalog_cache")? {
        if cached.is_object()
            && cached
                .get("catalogs")
                .and_then(Value::as_object)
                .map(|m| !m.is_empty())
                .unwrap_or(false)
        {
            return Ok(cached);
        }
    }
    let mut phases = serde_json::Map::new();
    for &(code, label) in STUDY_PHASES {
        phases.insert(code.to_string(), Value::String(label.to_string()));
    }
    Ok(json!({
        "study_phases": phases,
        "subjects": {},
        "catalogs": {},
    }))
}

pub async fn refresh_catalogs(base_settings: &AppSettings, store: &SqliteStore) -> AppResult<Value> {
    let effective = store.effective_settings(base_settings)?;
    let client = StzyHttpClient::new(effective, store.clone(), None, None, None);

    let subj_data = client
        .get_json("/zw-zzw/api/v1/zzw/tag/getStudyPhaseSubjectTagData", None, "")
        .await?;
    let mut subjects_map = serde_json::Map::new();
    for &(code, _) in STUDY_PHASES {
        subjects_map.insert(code.to_string(), json!({}));
    }
    if let Some(items) = subj_data.get("data").and_then(Value::as_array) {
        for item in items {
            let phase_code = extract_code(item, &["dictCode"]);
            let Some(Value::Object(ref mut phase_obj)) = subjects_map.get_mut(&phase_code) else {
                continue;
            };
            if let Some(children) = item.get("childList").and_then(Value::as_array) {
                for child in children {
                    let c_code = extract_code(child, &["dictCode"]);
                    let c_name = extract_name(child, &["dictName"]);
                    if !c_code.is_empty() && !c_name.is_empty() {
                        phase_obj.insert(c_code, Value::String(c_name));
                    }
                }
            }
        }
    }

    let mut catalogs_map = serde_json::Map::new();
    let mut phases_map = serde_json::Map::new();
    for &(phase_code, phase_label) in STUDY_PHASES {
        phases_map.insert(phase_code.to_string(), Value::String(phase_label.to_string()));
        let catalog = TagCatalog::fetch(&client, phase_code).await?;
        catalogs_map.insert(phase_code.to_string(), serde_json::to_value(&catalog.tags)?);
    }

    let payload = json!({
        "study_phases": phases_map,
        "subjects": subjects_map,
        "catalogs": catalogs_map,
    });
    store.set_kv("catalog_cache", &payload)?;
    Ok(payload)
}
