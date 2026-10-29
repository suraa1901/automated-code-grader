// Dynamic "add test case" rows on the new-assignment form.
document.addEventListener("DOMContentLoaded", () => {
  const addBtn = document.getElementById("add-testcase");
  const list = document.getElementById("testcase-list");
  const template = document.getElementById("testcase-template");

  function addRow() {
    const rowIndex = list.children.length; // matches the order test_input/test_output arrive server-side
    const clone = template.content.cloneNode(true);
    const checkbox = clone.querySelector(".hidden-checkbox");
    if (checkbox) checkbox.value = String(rowIndex);
    list.appendChild(clone);
  }

  if (addBtn) {
    addBtn.addEventListener("click", addRow);
    addRow(); // start with one row so the form isn't empty
  }

  // Color similarity bars by how close they are to the assignment's flag threshold.
  document.querySelectorAll("[data-sim]").forEach((el) => {
    const value = parseFloat(el.dataset.sim);
    let color = "#4fb286"; // teal - low similarity
    if (value >= 70) color = "#d9584f";       // coral - high, likely flagged
    else if (value >= 40) color = "#e0a458";  // amber - moderate
    el.style.background = color;
    el.style.width = Math.min(value, 100) + "%";
  });
});
