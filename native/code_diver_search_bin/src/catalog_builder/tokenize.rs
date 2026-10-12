pub fn tokenize(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    for part in text
        .split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|p| !p.is_empty())
    {
        let chars: Vec<char> = part.chars().collect();
        let mut start = 0;
        for i in 1..chars.len() {
            let (prev, cur) = (chars[i - 1], chars[i]);
            let boundary =
                (prev.is_ascii_lowercase() || prev.is_ascii_digit()) && cur.is_ascii_uppercase();
            let acronym = prev.is_ascii_uppercase()
                && cur.is_ascii_uppercase()
                && chars.get(i + 1).is_some_and(|n| n.is_ascii_lowercase());
            if boundary || acronym {
                out.push(chars[start..i].iter().collect::<String>());
                start = i;
            }
        }
        out.push(chars[start..].iter().collect::<String>());
    }
    out.into_iter()
        .filter(|t| t.len() >= 2)
        .map(|t| t.to_lowercase())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ascii_camel_acronyms_and_short_tokens() {
        assert_eq!(
            tokenize("XMLParser2Go x é bb"),
            vec!["xml", "parser2", "go", "bb"]
        );
        assert_eq!(tokenize("a/b::file_summary"), vec!["file", "summary"]);
    }
}
