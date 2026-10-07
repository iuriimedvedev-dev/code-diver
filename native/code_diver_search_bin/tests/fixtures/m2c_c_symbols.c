#include "worker.h"
struct Forward;
struct Worker {
    int value;
};
enum Mode { MODE_READY };
typedef struct Alias { int value; } Alias;
static int process_task(int value) { return value; }
int *missed_pointer(void) { return 0; }
int* matched_pointer(void) { return 0; }
int prototype(void);
int multiline(void)
{
    return 0;
}