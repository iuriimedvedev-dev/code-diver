// Synthetic TS/JS regex surface; intentionally not valid TypeScript throughout.
export default abstract class Zoo<T> {}
export interface Shape { size: number }
export type Alias<T> = T | null;
export const arrow = async (x) => x;
const expression = function named() {};
export default async function* generator<T>(x: T) {}
export let value = 1, ignored = 2;
const localValue = 3;
export const typedReturn = (x): number => x;
export const genericArrow = <T>(x: T) => x;
export const nestedParams = (x = call()) => x;
/*
  class CommentLeak {}
*/
* class Skipped {}
  function Nested() {} // signature retains trailing comment
export const $cash$ = x => x;
class Aé²漢 {}
export { value as renamed };
export enum Unsupported { A }
class Z {} class SecondIgnored {}