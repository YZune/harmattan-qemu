/*
 * Copyright (C) 2026 YZune and contributors.
 * SPDX-License-Identifier: Apache-2.0
 * Web adaptation: equal-corner cubic paths, inset surfaces and resize handling.
 * License: ../../LICENSES/Apache-2.0.txt
 */
(() => {
  "use strict";

  if (!window.ResizeObserver || !CSS.supports("clip-path", 'path("M0 0H1V1Z")')) return;

  function cobblePath(width, height, corner, inset = 0) {
    const left = inset;
    const top = inset;
    const right = width - inset;
    const bottom = height - inset;
    const radius = Math.max(0, Math.min(corner - inset, (right - left) / 2, (bottom - top) / 2));
    // Same control points as Compose: 2 * cornerSize * f, with f = 0.125.
    const control = radius * 0.25;
    return `path("M ${left} ${top + radius}
      C ${left} ${top + control} ${left + control} ${top} ${left + radius} ${top}
      L ${right - radius} ${top}
      C ${right - control} ${top} ${right} ${top + control} ${right} ${top + radius}
      L ${right} ${bottom - radius}
      C ${right} ${bottom - control} ${right - control} ${bottom} ${right - radius} ${bottom}
      L ${left + radius} ${bottom}
      C ${left + control} ${bottom} ${left} ${bottom - control} ${left} ${bottom - radius}
      Z")`.replace(/\s+/g, " ");
  }

  function update(element) {
    const { width, height } = element.getBoundingClientRect();
    if (width <= 2 || height <= 2) return;
    const requestedCorner = Number(element.dataset.cobbleCorner);
    const corner = requestedCorner > 0 ? Math.min(requestedCorner, width / 2, height / 2) : Math.min(width, height) / 2;
    element.style.setProperty("--cobble-path", cobblePath(width, height, corner));
    element.style.setProperty("--cobble-inset-path", cobblePath(width, height, corner, 1));
    element.classList.add("cobble-ready");
  }

  const observer = new ResizeObserver(entries => {
    for (const { target } of entries) update(target);
  });
  for (const element of document.querySelectorAll(".cobble")) {
    update(element);
    observer.observe(element);
  }
})();
