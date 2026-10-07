use serde_json::{Map, Value};

// M1 reads only the scanner section; unrelated service configuration is never logged.
pub fn parse(raw: &str, is_toml: bool) -> Result<Value, String> {
    if is_toml {
        let value: toml::Value = toml::from_str(raw).map_err(|_| "Invalid TOML configuration")?;
        return serde_json::to_value(value).map_err(|_| "Invalid TOML configuration".into());
    }
    let mut scanner = Map::new();
    let mut active = false;
    let mut list_key: Option<String> = None;
    for (index, line) in raw.lines().enumerate() {
        let error = || {
            format!(
                "Unsupported or invalid scanner YAML at line {}; use scalar values and block/flow lists (anchors and tags are not supported in M1)",
                index + 1
            )
        };
        let line = without_comment(line).map_err(|_| error())?;
        if line.trim().is_empty() {
            continue;
        }
        if !line.starts_with(' ') && !line.starts_with('\t') {
            active = line.trim() == "scanner:";
            list_key = None;
            continue;
        }
        if !active {
            continue;
        }
        if line.contains('\t') {
            return Err(error());
        }
        let stripped = line.trim();
        if let Some(item) = stripped.strip_prefix("- ") {
            let key = list_key.as_ref().ok_or_else(error)?;
            let array = scanner
                .get_mut(key)
                .and_then(Value::as_array_mut)
                .ok_or_else(error)?;
            array.push(scalar(item).map_err(|_| error())?);
            continue;
        }
        let (key, value) = stripped.split_once(':').ok_or_else(error)?;
        if key.is_empty() || key.contains([' ', '&', '*', '!']) || scanner.contains_key(key) {
            return Err(error());
        }
        let value = value.trim();
        if value.is_empty() && matches!(key, "include" | "exclude") {
            scanner.insert(key.into(), Value::Array(vec![]));
            list_key = Some(key.into());
        } else {
            scanner.insert(key.into(), scalar(value).map_err(|_| error())?);
            list_key = None;
        }
    }
    Ok(serde_json::json!({"scanner": scanner}))
}

fn without_comment(line: &str) -> Result<&str, ()> {
    let mut quote = None;
    let mut escape = false;
    let mut previous = ' ';
    for (index, character) in line.char_indices() {
        if escape {
            escape = false;
            previous = character;
            continue;
        }
        if quote == Some('"') && character == '\\' {
            escape = true;
            continue;
        }
        if matches!(character, '\'' | '"') {
            if quote == Some(character) {
                quote = None;
            } else if quote.is_none() {
                quote = Some(character);
            }
        }
        if character == '#' && quote.is_none() && previous.is_whitespace() {
            return Ok(&line[..index]);
        }
        previous = character;
    }
    if quote.is_some() { Err(()) } else { Ok(line) }
}

fn scalar(value: &str) -> Result<Value, ()> {
    let value = value.trim();
    if value.starts_with('"') {
        return serde_json::from_str(value).map_err(|_| ());
    }
    if value.starts_with('\'') && value.ends_with('\'') && value.len() >= 2 {
        return Ok(Value::String(value[1..value.len() - 1].replace("''", "'")));
    }
    if let Some(inner) = value.strip_prefix('[').and_then(|v| v.strip_suffix(']')) {
        let mut values = Vec::new();
        let mut start = 0;
        let mut quote = None;
        let mut escape = false;
        for (index, c) in inner.char_indices() {
            if escape {
                escape = false;
                continue;
            }
            if c == '\\' && quote == Some('"') {
                escape = true;
                continue;
            }
            if matches!(c, '\'' | '"') {
                if quote == Some(c) {
                    quote = None;
                } else if quote.is_none() {
                    quote = Some(c);
                }
            }
            if c == ',' && quote.is_none() {
                values.push(scalar(&inner[start..index])?);
                start = index + 1;
            }
        }
        if !inner[start..].trim().is_empty() {
            values.push(scalar(&inner[start..])?);
        }
        return Ok(Value::Array(values));
    }
    match value {
        "" | "null" | "Null" | "NULL" | "~" => Ok(Value::Null),
        "true" | "True" | "TRUE" => Ok(Value::Bool(true)),
        "false" | "False" | "FALSE" => Ok(Value::Bool(false)),
        _ => {
            if value.starts_with(['&', '*', '!', '|', '>', '{', '[', '\'', '"']) {
                return Err(());
            }
            if let Ok(number) = value.parse::<i64>() {
                return Ok(Value::from(number));
            }
            Ok(Value::String(value.into()))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scanner_block_and_flow_lists() {
        let config = parse("root: .\nscanner:\n  include:\n    - repos/**\n    - '.github/**'\n  exclude: [\"**/.git/**\", 'tmp/**'] # comment\n  max_file_bytes: 1000000\n  file_summary_compact_budget: true\n", false).unwrap();
        assert_eq!(
            config["scanner"]["include"],
            serde_json::json!(["repos/**", ".github/**"])
        );
        assert_eq!(
            config["scanner"]["exclude"],
            serde_json::json!(["**/.git/**", "tmp/**"])
        );
    }

    #[test]
    fn rejects_anchors_and_duplicate_keys_without_echoing_values() {
        assert!(parse("scanner:\n  include: &secret [a]\n", false).is_err());
        assert!(parse("scanner:\n  include: []\n  include: []\n", false).is_err());
    }
}
