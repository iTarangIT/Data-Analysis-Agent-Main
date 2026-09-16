/**
 * Whether the desktop sidebar is folded down to its icon rail.
 *
 * A cookie rather than localStorage, so the layout can read it on the server and the first
 * paint is already the right width. localStorage would render wide and then snap narrow.
 *
 * Kept out of the client module on purpose: a server component that imports a constant from
 * a "use client" file gets a client reference, not the string.
 */
export const SIDEBAR_COOKIE = "sidebar_collapsed";
