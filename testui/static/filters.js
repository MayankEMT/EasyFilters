/* The filter panel.
 *
 * One rule holds the whole thing together: `state.filter` is the single source
 * of truth, and it is always the exact 25-key JSON the Smart Filter API speaks.
 * Clicking a checkbox edits it; the chat box edits it; both then redraw from it
 * and re-run the search. Nothing keeps a second copy of "what is checked".
 *
 * That is what makes the panel a real test of the contract - whatever you tick
 * here is what gets sent back as `currentFilter` on the next prompt, so
 * "also make it morning" has to build on your clicks.
 */

const RANGE_FIELDS = ["Price", "DepTime", "ArrTime", "Duration"];
const LIST_FIELDS = ["Stop", "Airline", "Layover", "AirCarftType",
                     "TakeOffAirport", "LandingAirport"];
const BOOL_FIELDS = ["Refundable", "IsWifi", "IsRedEyes"];

const SORT_VALUES = ["Best", "Cheapest", "Fastest", "Early Take-off",
                     "Late Take-off", "Early Arrival", "Late Arrival",
                     "Slowest", "Highest Price"];

/* Time-of-day buttons, matching the presets the API resolves server-side so a
 * click and the words "morning flights" produce the same filter. */
const TIME_WINDOWS = [
  ["Before 6 AM", "00:00", "06:00"],
  ["6 AM – 12 PM", "06:00", "12:00"],
  ["12 PM – 6 PM", "12:00", "18:00"],
  ["After 6 PM",  "18:00", "23:59"],
];

function emptyFilter() {
  const f = {};
  for (const k of RANGE_FIELDS) { f["Is" + k] = false; f[k] = { Min: "", Max: "" }; }
  for (const k of LIST_FIELDS)  { f["Is" + k] = false; f[k] = []; }
  for (const k of BOOL_FIELDS)  f[k] = false;
  f.IsSortBy = false; f.SortBy = "";
  return f;
}

/* The API computes these server-side; we mirror it so a click-built filter is
 * byte-identical to a chat-built one. */
function recomputeFlags(f) {
  for (const k of RANGE_FIELDS) f["Is" + k] = !!(f[k].Min || f[k].Max);
  for (const k of LIST_FIELDS)  f["Is" + k] = f[k].length > 0;
  f.IsSortBy = !!f.SortBy;
  return f;
}

/* Facets arrive as "HYD:Hyderabad" or plain "IndiGo". The value before the
 * colon is what goes in the filter; the label is only for display. */
function parseFacet(csv) {
  if (!csv) return [];
  return csv.split(",").map(s => s.trim()).filter(Boolean).map(entry => {
    const i = entry.indexOf(":");
    return i === -1
      ? { value: entry, label: entry }
      : { value: entry.slice(0, i).trim(), label: entry.slice(i + 1).trim() || entry };
  });
}

const money = n => "₹" + Number(n).toLocaleString("en-IN");

function buildPanel(facets, ranges, filter, onChange) {
  const f = filter;
  const leg = Array.isArray(facets) ? facets[0] : (facets || {});
  const out = [];

  const group = (title, body) =>
    `<div class="fgroup"><h3>${title}</h3>${body}</div>`;

  const checks = (field, entries) => entries.map(e => {
    const on = (f[field] || []).some(v => String(v) === String(e.value));
    return `<label class="ck"><input type="checkbox" data-field="${field}"
      data-value="${String(e.value).replace(/"/g, "&quot;")}" ${on ? "checked" : ""}>
      <span>${e.label}</span></label>`;
  }).join("");

  /* ---- stops ---- */
  const stopOpts = (ranges?.stops?.length ? ranges.stops : [0, 1, 2])
    .map(n => ({ value: n, label: n === 0 ? "Non-stop" : n === 1 ? "1 stop" : n + " stops" }));
  out.push(group("Stops", checks("Stop", stopOpts)));

  /* ---- price ---- */
  if (ranges?.price) {
    const { min, max } = ranges.price;
    const cur = Number(f.Price.Max) || max;
    out.push(group("Price", `
      <input type="range" id="priceRange" min="${min}" max="${max}" step="100" value="${cur}">
      <div class="rowends"><span>${money(min)}</span><span id="priceNow">${money(cur)}</span></div>`));
  }

  /* ---- departure / arrival windows ---- */
  const windows = (field) => TIME_WINDOWS.map(([label, lo, hi]) => {
    const on = f[field].Min === lo && f[field].Max === hi;
    return `<button class="tw ${on ? "on" : ""}" data-field="${field}"
      data-lo="${lo}" data-hi="${hi}">${label}</button>`;
  }).join("");
  out.push(group("Departure", `<div class="twrap">${windows("DepTime")}</div>`));
  out.push(group("Arrival", `<div class="twrap">${windows("ArrTime")}</div>`));

  /* ---- duration ---- */
  if (ranges?.duration) {
    const { min, max } = ranges.duration;
    const cur = Number(f.Duration.Max) || max;
    out.push(group("Max duration", `
      <input type="range" id="durRange" min="${min}" max="${max}" step="5" value="${cur}">
      <div class="rowends"><span>${Math.floor(min / 60)}h ${min % 60}m</span>
        <span id="durNow">${Math.floor(cur / 60)}h ${cur % 60}m</span></div>`));
  }

  /* ---- facet-driven lists ---- */
  const lists = [
    ["Airlines", "Airline", leg.airline],
    ["Layover", "Layover", leg.layover],
    ["Aircraft", "AirCarftType", leg.airCarftType],
    ["Departure airport", "TakeOffAirport", leg.takeOffAirport],
    ["Arrival airport", "LandingAirport", leg.landingAirport],
  ];
  for (const [title, field, csv] of lists) {
    const entries = parseFacet(csv);
    if (!entries.length) continue;
    const many = entries.length > 6;
    out.push(group(title,
      `<div class="scroll${many ? " tall" : ""}">${checks(field, entries)}</div>`));
  }

  /* ---- plain booleans ---- */
  out.push(group("More", BOOL_FIELDS.map(k =>
    `<label class="ck"><input type="checkbox" data-bool="${k}" ${f[k] ? "checked" : ""}>
     <span>${k === "Refundable" ? "Refundable" : k === "IsWifi" ? "Wifi" : "Red-eye"}</span></label>`
  ).join("")));

  document.querySelector("#filterBody").innerHTML = out.join("");
  wire(f, onChange);
}

function wire(f, onChange) {
  const body = document.querySelector("#filterBody");

  body.querySelectorAll("input[data-field]").forEach(box => {
    box.onchange = () => {
      const field = box.dataset.field;
      let raw = box.dataset.value;
      const value = field === "Stop" ? Number(raw) : raw;
      const list = f[field].filter(v => String(v) !== String(value));
      f[field] = box.checked ? [...list, value] : list;
      onChange(recomputeFlags(f));
    };
  });

  body.querySelectorAll("button.tw").forEach(btn => {
    btn.onclick = () => {
      const { field, lo, hi } = btn.dataset;
      const already = f[field].Min === lo && f[field].Max === hi;
      f[field] = already ? { Min: "", Max: "" } : { Min: lo, Max: hi };
      onChange(recomputeFlags(f));
    };
  });

  body.querySelectorAll("input[data-bool]").forEach(box => {
    box.onchange = () => { f[box.dataset.bool] = box.checked; onChange(recomputeFlags(f)); };
  });

  const price = body.querySelector("#priceRange");
  if (price) {
    price.oninput = () => body.querySelector("#priceNow").textContent = money(price.value);
    price.onchange = () => {
      f.Price = { Min: "", Max: price.value === price.max ? "" : String(price.value) };
      onChange(recomputeFlags(f));
    };
  }

  const dur = body.querySelector("#durRange");
  if (dur) {
    dur.oninput = () => {
      const v = +dur.value;
      body.querySelector("#durNow").textContent = `${Math.floor(v / 60)}h ${v % 60}m`;
    };
    dur.onchange = () => {
      f.Duration = { Min: "", Max: dur.value === dur.max ? "" : String(dur.value) };
      onChange(recomputeFlags(f));
    };
  }
}

function buildSortBar(filter, onChange) {
  const html = ["Best", "Cheapest", "Fastest", "Early Take-off", "Late Arrival"]
    .map(v => `<button class="sortbtn ${filter.SortBy === v ? "on" : ""}" data-sort="${v}">${v}</button>`)
    .join("") +
    `<select id="sortMore"><option value="">Other sort…</option>` +
    SORT_VALUES.map(v => `<option ${filter.SortBy === v ? "selected" : ""}>${v}</option>`).join("") +
    `</select>`;
  const bar = document.querySelector("#sortbar");
  bar.innerHTML = html;
  bar.querySelectorAll("button[data-sort]").forEach(b => b.onclick = () => {
    filter.SortBy = filter.SortBy === b.dataset.sort ? "" : b.dataset.sort;
    onChange(recomputeFlags(filter));
  });
  bar.querySelector("#sortMore").onchange = e => {
    filter.SortBy = e.target.value;
    onChange(recomputeFlags(filter));
  };
}
