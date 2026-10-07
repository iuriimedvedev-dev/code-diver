// Synthetic regex input, deliberately not valid Rust.
pub(crate) struct Store<T> {
    field: T,
}
pub enum Mode { On, Off }
pub unsafe trait Service {
    fn perform(&self);
}
impl<T> pkg::Service<T> for pkg::Store<T> {
    pub async fn run(&self) {}
}
impl Vec<Vec<T>> {}
macro_rules! dispatch { () => {} }
pub(in crate::private) macro visible {}
macro private {}
pub default const async unsafe extern "C" fn all_modifiers() {}
extern fn no_abi() {}
fn r#raw() {}
fn Name²界() {}
fn Namé() {}
/* open comment
fn apparent_comment_member() {}
*/
#[attribute] fn ignored_same_line() {}
#[attribute]
fn attached() {}
pub(other) struct ignored_visibility;
unsafe async fn ignored_order() {}
macro_rules!NoSpace {}
type Alias = u8;
const VALUE: u8 = 1;
impl Trait for &Type {}
struct First; enum NotSecond {}
fn repeated() {}
fn repeated() {}