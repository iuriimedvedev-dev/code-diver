package com.example.work;
/** Coordinates jobs. More details. */
public class WorkerServiceImpl extends Base implements API {
    public WorkerServiceImpl() {}
    protected <T> T run(T value) { return value; }
    private void reset() {}
}
public @interface Marker {}
non-sealed class Child {}
record Row(int value) {}
enum Mode { ON }