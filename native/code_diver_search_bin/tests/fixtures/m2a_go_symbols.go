package synthetic

// func Ignored() {}
type Zebra struct {}
type Reader interface { Read() }
type Count int
type Alias = Count
type Box[T any] struct { Value T }
type (
    Grouped struct {}
    GroupInterface interface {}
    GroupAlias int
)
func (r *Zebra) Run() {}
func Free[T any](x T) T { return x }
func (Zebra) Bare() {}
func (r *Box[T]) Unsupported() {}