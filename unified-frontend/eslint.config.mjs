// ESLint 9 flat config — replaces the old .eslintrc.json (ESLint 9
// no longer reads .eslintrc.* by default, and `next lint` has been
// removed as of Next 16), migrating its exact
// `extends: ["next/core-web-vitals", "next/typescript"]` to the flat
// equivalent per Next's own migration guide.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [...nextCoreWebVitals, ...nextTypescript];

export default config;
