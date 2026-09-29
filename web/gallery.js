const cards = [...document.querySelectorAll(".gallery > article")];
document.querySelector("#total").textContent = String(cards.length).padStart(2, "0");
const form = document.querySelector('form[aria-label="筛选作品"]');
const facets = [...form.querySelectorAll("[data-facet]")];
const names = facets.map(facet => facet.dataset.facet);
const lists = Object.fromEntries(facets.map(facet => [facet.dataset.facet, facet.querySelector("[data-options-for]")]));
const applied = Object.fromEntries(names.map(name => [name, []]));
const selectedIn = name => [...lists[name].querySelectorAll('input[type="checkbox"]:checked')].map(box => box.value);
const draftState = () => Object.fromEntries(names.map(name => [name, selectedIn(name)]));
const valuesFor = (name, state) => [...new Set(cards.filter(card => names.every(other => {
  const values = state[other] || [];
  return other === name || !values.length || values.includes(card.dataset[other]);
})).map(card => card.dataset[name]))].sort();
function matches(card, state) { return names.every(name => {
  const values = state[name] || [];
  return !values.length || values.includes(card.dataset[name]);
}); }
function buildList(name, values, checkedValues) {
  const list = lists[name];
  const scrollTop = list.scrollTop;
  const checked = new Set(checkedValues);
  list.replaceChildren(...values.map(value => {
    const label = document.createElement("label");
    label.className = "check-item";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = value;
    box.checked = checked.has(value);
    const text = document.createElement("span");
    text.className = "check-text";
    text.textContent = value;
    text.title = value;
    label.append(box, text);
    return label;
  }));
  if (!values.length) {
    const empty = document.createElement("div");
    empty.className = "check-empty";
    empty.textContent = "暂无";
    list.append(empty);
  }
  document.querySelector(`[data-count-for="${name}"]`).textContent = `· ${values.length}`;
  list.scrollTop = scrollTop;
}
function updateAllOptions(state) {
  for (const name of names) buildList(name, valuesFor(name, state), state[name] || []);
  updateScrollHints();
}
function updateOtherOptions(changedName, state) {
  for (const name of names) {
    if (name === changedName) continue;
    buildList(name, valuesFor(name, state), state[name] || []);
  }
  document.querySelector(`[data-count-for="${changedName}"]`).textContent = `· ${valuesFor(changedName, state).length}`;
  updateScrollHints();
}
function updateScrollHints() {
  for (const name of names) {
    const list = lists[name];
    const overflow = list.scrollHeight - list.clientHeight;
    list.classList.toggle("has-more", overflow > 4 && overflow - list.scrollTop > 4);
  }
}
function render() {
  let visible = 0;
  for (const card of cards) {
    card.hidden = !matches(card, applied);
    if (!card.hidden) visible++;
  }
  document.querySelector("#count").textContent = `${visible} / ${cards.length} 作品`;
  document.querySelector("#empty").hidden = visible !== 0;
}
form.addEventListener("submit", event => event.preventDefault());
function writeURL() {
  const params = new URLSearchParams();
  for (const name of names) for (const value of applied[name]) params.append(name, value);
  const query = params.toString();
  try {
    history.replaceState(null, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
  } catch {
    // file:// 本地预览不支持 replaceState，忽略即可。
  }
}
function readURL() {
  const params = new URLSearchParams(location.search);
  for (const name of names) {
    const known = new Set(cards.map(card => card.dataset[name]));
    const kept = [];
    for (const raw of params.getAll(name)) {
      if (known.has(raw)) { if (!kept.includes(raw)) kept.push(raw); continue; }
      for (const part of raw.split(",")) {
        const value = part.trim();
        if (known.has(value) && !kept.includes(value)) kept.push(value);
      }
    }
    applied[name] = kept;
  }
}
function apply(changedName) {
  Object.assign(applied, draftState());
  if (changedName) updateOtherOptions(changedName, applied);
  else updateAllOptions(applied);
  render(); writeURL();
}
for (const facet of facets) {
  const name = facet.dataset.facet;
  lists[name].addEventListener("change", () => apply(name));
  lists[name].addEventListener("scroll", updateScrollHints);
}
window.addEventListener("resize", updateScrollHints);
form.addEventListener("reset", event => {
  event.preventDefault();
  for (const name of names) applied[name] = [];
  updateAllOptions(applied); render(); writeURL();
});
const copyButton = document.querySelector("#copy-link");
copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(location.href);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = location.href;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  const original = copyButton.textContent;
  copyButton.textContent = "已复制 ✓";
  setTimeout(() => { copyButton.textContent = original; }, 1500);
});
const copyPromptButton = document.querySelector("#copy-prompt");
copyPromptButton.addEventListener("click", async () => {
  const text = document.querySelector("#artwork-prompt").textContent.trim();
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  const original = copyPromptButton.textContent;
  copyPromptButton.textContent = "已复制 ✓";
  setTimeout(() => { copyPromptButton.textContent = original; }, 1500);
});
const copyCandyButton = document.querySelector("#copy-candy");
copyCandyButton.addEventListener("click", async () => {
  const text = document.querySelector("#candy-cmd").textContent.trim();
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  const original = copyCandyButton.textContent;
  copyCandyButton.textContent = "已复制 ✓";
  setTimeout(() => { copyCandyButton.textContent = original; }, 1500);
});
readURL();
updateAllOptions(applied); render(); writeURL();
const viewer = document.querySelector("dialog");
const viewerFrame = viewer.querySelector("iframe");
document.querySelector(".gallery").addEventListener("click", event => {
  const button = event.target.closest(".expand");
  if (!button) return;
  const card = button.closest("article");
  document.querySelector("#viewer-title").textContent = [...card.querySelectorAll(".meta-text")].map(el => el.textContent).join(" · ");
  viewerFrame.src = card.querySelector("iframe").src;
  viewer.showModal();
});
document.querySelector("#close-viewer").addEventListener("click", () => viewer.close());
viewer.addEventListener("close", () => viewerFrame.removeAttribute("src"));
viewer.addEventListener("click", event => {
  if (event.target !== viewer) return;
  const rect = viewer.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) viewer.close();
});

{
  // Deep links open the collapsed panel that holds the target.
  const openAnchor = () => {
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch { return; }
    if (!target) return;
    for (let parent = target; parent; parent = parent.parentElement) if (parent.tagName === "DETAILS") parent.open = true;
    requestAnimationFrame(() => target.scrollIntoView());
  };
  if (["model", "effort", "provider", "harness"].some(key => new URLSearchParams(location.search).has(key))) {
    document.getElementById("artwork-panel").open = true;
    window.dispatchEvent(new Event("resize"));
  }
  document.querySelectorAll(".support-panel").forEach(panel => panel.addEventListener("toggle", () => window.dispatchEvent(new Event("resize"))));
  window.addEventListener("hashchange", openAnchor);
  openAnchor();
}
