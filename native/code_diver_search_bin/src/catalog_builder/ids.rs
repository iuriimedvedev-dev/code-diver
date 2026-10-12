use sha1::{Digest, Sha1};

pub fn item_id(path: &str, kind: &str) -> String {
    let salt = kind.replace('_', "-");
    let digest = Sha1::digest(format!("{path}:{salt}").as_bytes());
    let hex: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
    format!("{path}::{kind}#{}", &hex[..12])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha1_contract() {
        assert_eq!(
            item_id("kb/aws/readme.md", "file_summary"),
            "kb/aws/readme.md::file_summary#c2a5f8c31968"
        );
        assert_eq!(
            item_id("kb/aws/readme.md", "file_manifest"),
            "kb/aws/readme.md::file_manifest#4061d3024820"
        );
    }
}
