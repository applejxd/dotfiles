"use strict";

const helpers = require("../assets/pptxgenjs_helpers");

const required = [
  "imageSizingContain",
  "imageSizingCrop",
  "safeOuterShadow",
  "warnIfSlideHasOverlaps",
  "warnIfSlideElementsOutOfBounds",
  "autoFontSize",
];

for (const name of required) {
  if (typeof helpers[name] !== "function") {
    throw new Error(`Missing helper export: ${name}`);
  }
}

console.log("PptxGenJS helpers are loadable.");
