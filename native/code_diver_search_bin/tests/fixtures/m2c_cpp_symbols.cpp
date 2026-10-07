// Synthetic reference-derived C/C++ declarations.
#include <vector>
class Forward;
struct Packet {
};
enum class State { Ready };
template<class T> class Box {
};
explicit Packet() {}
Packet::Packet() : value(1) {}
Packet::~Packet() {}
int Packet::read() const noexcept { return 1; }
extern "C" int api() { return 0; }
static inline int freeFn(int x) { return x; }
int prototype();
int multiline()
{
}
/* comment begins
int inComment() {}
*/