// The first column of a table holds labels (an option, a variable, a method): when all of them are short, none wraps.
// A table whose first column holds sentences keeps its normal wrapping, so it cannot be stretched.
document.querySelectorAll(".md-typeset table:not([class])").forEach((table) => {
  const cells = [...table.querySelectorAll("tbody td:first-child")];
  if (cells.length && cells.every((cell) => cell.textContent.trim().length <= 60)) {
    table.querySelectorAll(":is(th, td):first-child").forEach((cell) => cell.classList.add("nowrap"));
  }
});
