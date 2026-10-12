package com.example.work
/** Handles work. Another sentence. */
internal class WorkHandler(x: Int) : Base(x), API {
    override suspend fun execute() {}
    private fun String.clean() = trim()
}
annotation class Marker
enum class Mode { ON }
object Registry {}
inline fun <T> pkg.Type.map(value: T) = value
fun synchronized() {}