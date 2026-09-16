import { createCodePlugin } from "@streamdown/code";
import { createMathPlugin } from "@streamdown/math";
import { createCssVariablesTheme } from "shiki/core";

/**
 * How the Response component renders an answer's markdown beyond the basics.
 *
 * Code is highlighted by shiki with a theme whose every colour is a CSS custom property, set in
 * globals.css from the palette. Streamdown's default GitHub themes would bring their own reds
 * and blues; this way code in an answer sits on the same dark surface as the SQL block and uses
 * nothing the palette does not already have. One theme for both slots, because the product has
 * no dark mode.
 *
 * Math is `$$...$$` only. Single-dollar inline math would read "$5 and $10" -- ordinary text in
 * an analytics answer -- as a formula and mangle it.
 */

const paletteTheme = createCssVariablesTheme({
  name: "analyst-palette",
  variablePrefix: "--code-",
  fontStyle: true,
});

export const SHIKI_THEME: [typeof paletteTheme, typeof paletteTheme] = [paletteTheme, paletteTheme];

export const ANSWER_PLUGINS = {
  code: createCodePlugin({ themes: SHIKI_THEME }),
  math: createMathPlugin({ singleDollarTextMath: false, errorColor: "var(--fault)" }),
};
