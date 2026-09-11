const cards = [...document.querySelectorAll("article")];
const form = document.querySelector("form");
const selects = [...form.querySelectorAll("select")];
for (const select of selects) {
  const values = [...new Set(cards.map(card => card.dataset[select.name]))].sort();
  for (const value of values) select.add(new Option(value, value));
}
function filter() {
  let visible = 0;
  for (const card of cards) {
    card.hidden = !selects.every(select => !select.value || card.dataset[select.name] === select.value);
    if (!card.hidden) visible++;
  }
  document.querySelector("#count").textContent = `${visible} / ${cards.length} 作品`;
  document.querySelector("#empty").hidden = visible !== 0;
}
form.addEventListener("change", filter);
form.addEventListener("reset", () => setTimeout(filter, 0));
form.addEventListener("submit", event => event.preventDefault());
filter();
