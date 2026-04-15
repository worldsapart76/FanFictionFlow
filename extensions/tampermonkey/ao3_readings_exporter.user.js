// ==UserScript==
// @name         AO3 Readings To-Read Exporter (Page -> CSV/JSON)
// @match        https://archiveofourown.org/users/worldsapart/readings*
// @run-at       document-end
// @grant        none
// ==/UserScript==

(function () {
  "use strict";

const u = new URL(location.href);
const show = u.searchParams.get("show") || "to-read"; // AO3 defaults vary a bit
  if (!["to-read", "history"].includes(show)) return;

  const showTag = show.replace(/-/g, "_"); // "to-read" -> "to_read"


  const qs = (sel, root = document) => {
    if (!root) return null;
    return root.querySelector(sel);
  };

  const qsa = (sel, root = document) => {
    if (!root) return [];
    return Array.from(root.querySelectorAll(sel));
  };

  const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
  const TAG_DELIM = " ||| ";


  function toInt(textValue) {
    // AO3 uses commas in numbers like "12,345"
    const cleaned = norm(textValue).replace(/,/g, "");
    const n = parseInt(cleaned || "0", 10);
    return Number.isFinite(n) ? n : 0;
  }


  function getWorkIdFromHref(href) {
    const m = (href || "").match(/\/works\/(\d+)/);
    return m ? m[1] : "";
  }

  function escapeCsvCell(value) {
    const s = String(value ?? "");
    if (/[,"\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  }

  function downloadFile(filename, content, mime) {
    const blob = new Blob([content], { type: mime });
    const obj = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = obj;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(obj);
  }

  function getWorkItems(doc = document) {
    const list =
      qs("ol.work.index.group", doc) ||
      qs("ol.work.index", doc) ||
      qs("#main ol", doc) ||
      qs("ol", doc);

    if (!list) return [];
    let items = qsa("li.work", list);
    if (items.length === 0) items = qsa("li", list).filter(li => qs("a[href*='/works/']", li));
    return items;
  }

  function tagsByClass(tagRoot, className) {
    if (!tagRoot) return [];
    return qsa(`li.${className} a.tag`, tagRoot).map(a => norm(a.textContent)).filter(Boolean);
  }

  function parseWork(li) {
    const titleLink =
      qs("h4.heading a[href*='/works/']", li) ||
      qs("a[href*='/works/']", li);

    const href = titleLink ? titleLink.getAttribute("href") : "";
    const link = href ? new URL(href, location.origin).toString() : "";
    const work_id = getWorkIdFromHref(link);
    const title = norm(titleLink ? titleLink.textContent : "");

    const authors = qsa("a[rel='author']", li).map(a => norm(a.textContent)).filter(Boolean);
    const summary = norm(qs("blockquote.summary", li)?.textContent || "");

    const stats = qs("dl.stats", li);
    const words = toInt(qs("dd.words", stats)?.textContent || "0");

    const chaptersText = norm(qs("dd.chapters", stats)?.textContent || "");
    const [cur, total] = chaptersText.split("/").map(x => norm(x));
    const complete = total && total !== "?" && cur === total;

    const kudos = toInt(qs("dd.kudos", stats)?.textContent || "0");
    const hits = toInt(qs("dd.hits", stats)?.textContent || "0");
    const bookmarks = toInt(qs("dd.bookmarks", stats)?.textContent || "0");

const tagRoot = qs("ul.tags", li);

// Fandoms are often in a separate <h5 class="fandoms"> line, not inside ul.tags
let fandoms = qsa("h5.fandoms a.tag", li).map(a => norm(a.textContent)).filter(Boolean);

// Fallback (just in case AO3 ever puts them in ul.tags on some pages/skins)
if (fandoms.length === 0) {
  fandoms = tagsByClass(tagRoot, "fandoms");
}

const relationships = tagsByClass(tagRoot, "relationships");

    const characters = tagsByClass(tagRoot, "characters");
    const warnings = tagsByClass(tagRoot, "warnings");
    const categories = tagsByClass(tagRoot, "category");
    const additional_tags = tagsByClass(tagRoot, "freeforms");

    const rating = norm(qs("span.rating", li)?.textContent || "");
    const language = norm(qs("dd.language", stats)?.textContent || "");
    const updated_raw = norm(qs("p.datetime", li)?.textContent || "");
    const viewed_raw = norm(qs("h4.viewed", li)?.textContent || "");

    return {
      work_id, title, authors, link,
      fandoms, relationships, characters,
      warnings, categories, additional_tags,
      rating, language,
      words, chapters: chaptersText, complete,
      kudos, bookmarks, hits,
      updated_raw, viewed_raw,
      summary
    };
  }

  function getWorksOnPage(doc = document) {
    return getWorkItems(doc).map(parseWork).filter(w => w.work_id || w.title);
  }

  function worksToCSV(works) {
    const header = [
      "work_id","title","authors","link",
      "fandoms","relationship_primary", "relationship_additional","characters","warnings","categories",
      "rating","language","words","chapters","complete",
      "kudos","bookmarks","hits","updated_raw", "viewed_raw",
      "additional_tags","summary"
    ];

    const lines = [header.join(",")];

    for (const w of works) {
      const row = [
        w.work_id,
        w.title,
        (w.authors || []).join(TAG_DELIM),
        w.link,
        (w.fandoms || []).join(TAG_DELIM),

        // Primary relationship: first tag in AO3's relationship list
          (w.relationships && w.relationships.length ? w.relationships[0] : ""),

          // Additional relationships (everything after the first)
          (w.relationships && w.relationships.length > 1
           ? w.relationships.slice(1).join(TAG_DELIM)
           : ""),

        (w.characters || []).join(TAG_DELIM),
        (w.warnings || []).join(TAG_DELIM),
        (w.categories || []).join(TAG_DELIM),
        w.rating,
        w.language,
        w.words,
        "'" + (w.chapters || ""),
        w.complete ? "TRUE" : "FALSE",
        w.kudos,
        w.bookmarks,
        w.hits,
        w.updated_raw,
        (w.additional_tags || []).join(TAG_DELIM),
        w.summary
      ].map(escapeCsvCell);

      lines.push(row.join(","));
    }
    return lines.join("\n");
  }

  function exportThisPageJSON() {
    const works = getWorksOnPage();
    const payload = {
      exported_at: new Date().toISOString(),
      scope: "page",
      page: (u.searchParams.get("page") || "1"),
      count: works.length,
      works
    };
    downloadFile(`ao3_${showTag}_page_${payload.page}.json`, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
  }

  function exportThisPageCSV() {
    const page = (u.searchParams.get("page") || "1");
    const works = getWorksOnPage();
    downloadFile(`ao3_${showTag}_page_${page}.csv`, worksToCSV(works), "text/csv;charset=utf-8");
  }

  // Inject panel
  if (document.getElementById("ao3-export-panel")) return;

  const panel = document.createElement("div");
  panel.id = "ao3-export-panel";
  panel.style.position = "sticky";
  panel.style.top = "0";
  panel.style.zIndex = "99999";
  panel.style.background = "#fff3cd";
  panel.style.border = "2px solid #222";
  panel.style.padding = "10px";

  const bJson = document.createElement("button");
  bJson.textContent = "Export this page (JSON)";
  bJson.onclick = exportThisPageJSON;

  const bCsv = document.createElement("button");
  bCsv.textContent = "Export this page (CSV)";
  bCsv.style.marginLeft = "8px";
  bCsv.onclick = exportThisPageCSV;

  function sleep(ms) {
    return new Promise(res => setTimeout(res, ms));
  }

  function getLastPageNumber(doc = document) {
    // Best effort: read page numbers from AO3 pagination links
    const nums = qsa(".pagination a", doc)
      .map(a => a.getAttribute("href"))
      .filter(Boolean)
      .map(h => {
        try {
          return parseInt(new URL(h, location.origin).searchParams.get("page") || "1", 10);
        } catch {
          return 1;
        }
      })
      .filter(n => Number.isFinite(n));

    return nums.length ? Math.max(...nums) : 1;
  }

  function buildPageUrl(page) {
    const uu = new URL(location.href);
    uu.searchParams.set("show", show); // <-- use current tab
    uu.searchParams.set("page", String(page));
    return uu.toString();
  }

  async function fetchHtmlWithTimeout(url, ms, retries, setStatus) {
    for (let attempt = 1; attempt <= retries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), ms);

      try {
        const resp = await fetch(url, { credentials: "include", signal: controller.signal });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        // Timeout the body read too (some hangs occur here)
        const html = await Promise.race([
          resp.text(),
          new Promise((_, rej) => setTimeout(() => rej(new Error("TEXT_TIMEOUT")), ms))
        ]);

        return html;
      } catch (e) {
        const reason =
          e.name === "AbortError" ? "FETCH_TIMEOUT" :
          (e.message === "TEXT_TIMEOUT" ? "TEXT_TIMEOUT" : (e.message || "ERROR"));

        if (setStatus) setStatus(`Retry ${attempt}/${retries} (${reason})…`);
        await sleep(800 * attempt);

        if (attempt === retries) throw e;
      } finally {
        clearTimeout(timer);
      }
    }
  }

  async function exportAllPages(format, setStatus, setBusy) {
    const last = getLastPageNumber(document);
    const byId = new Map();

    setBusy(true);
    setStatus(`Found ${last} page(s). Fetching…`);

    for (let p = 1; p <= last; p++) {
      setStatus(`Fetching page ${p}/${last}…`);

      let html;
      try {
        html = await fetchHtmlWithTimeout(
          buildPageUrl(p),
          20000,   // timeout per attempt
          3,       // retries
          setStatus
        );
      } catch (e) {
        setStatus(`Skipped page ${p} after retries. Continuing…`);
        await sleep(900);
        continue;
      }

      const doc = new DOMParser().parseFromString(html, "text/html");
      const works = getWorksOnPage(doc);

      for (const w of works) {
        const key = w.work_id || w.link || `${w.title}|${(w.authors || []).join(",")}`;
        if (!byId.has(key)) byId.set(key, w);
      }

      // Polite delay so AO3 doesn't get hammered
      await sleep(900);
    }

    const all = Array.from(byId.values());
    setStatus(`Collected ${all.length} unique work(s). Downloading…`);

    const stamp = new Date().toISOString().slice(0, 10);

    if (format === "json") {
      const payload = {
        exported_at: new Date().toISOString(),
        scope: "all_pages",
        count: all.length,
        works: all
      };
      downloadFile(`ao3_to_read_ALL_${stamp}.json`, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
    } else {
      downloadFile(`ao3_to_read_ALL_${stamp}.csv`, worksToCSV(all), "text/csv;charset=utf-8");
    }

    setStatus(`Done. ✅ Exported ${all.length} unique work(s).`);
    setBusy(false);
  }

async function exportPageRange(format, startPage, endPage, setStatus, setBusy) {
  const byId = new Map();
  const skipped = [];

  setBusy(true);
  setStatus(`Exporting pages ${startPage}–${endPage}…`);

  for (let p = startPage; p <= endPage; p++) {
    setStatus(`Fetching page ${p}/${endPage}…`);
    const pageUrl = buildPageUrl(p);

    let html;
    try {
      html = await fetchHtmlWithTimeout(pageUrl, 20000, 3, setStatus);
    } catch (e) {
      skipped.push(p);
      setStatus(`Skipped page ${p} after retries. Continuing…`);
      await sleep(900);
      continue;
    }

    const doc = new DOMParser().parseFromString(html, "text/html");
    const works = getWorksOnPage(doc);
    if (works.length === 0) skipped.push(p);

    for (const w of works) {
      const key = w.work_id || w.link || `${w.title}|${(w.authors || []).join(",")}`;
      if (!byId.has(key)) byId.set(key, w);
    }

    await sleep(900);
  }

  const all = Array.from(byId.values());
  const stamp = new Date().toISOString().slice(0, 10);

  const rangeTag = `${startPage}-${endPage}`;
  setStatus(`Collected ${all.length} unique work(s). Downloading… (Skipped: ${skipped.length})`);

  if (format === "json") {
    const payload = {
      exported_at: new Date().toISOString(),
      scope: "page_range",
      page_range: rangeTag,
      count: all.length,
      skipped_pages: skipped,
      works: all
    };
    downloadFile(`ao3_to_read_${rangeTag}_${stamp}.json`, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
  } else {
    downloadFile(`ao3_to_read_${rangeTag}_${stamp}.csv`, worksToCSV(all), "text/csv;charset=utf-8");
  }

  setStatus(`Done. ✅ Exported ${all.length}. Skipped: ${skipped.join(", ") || "none"}`);
  setBusy(false);
}

    const startInput = document.createElement("input");
    startInput.type = "number";
    startInput.min = "1";
    startInput.value = "1";
    startInput.style.width = "70px";

    const endInput = document.createElement("input");
    endInput.type = "number";
    endInput.min = "1";
    endInput.value = "20";
    endInput.style.width = "70px";

    const label = document.createElement("span");
    label.style.marginLeft = "12px";
    label.style.fontSize = "12px";
    label.textContent = "Range:";

    const dash = document.createElement("span");
    dash.textContent = "–";
    dash.style.margin = "0 6px";

    const bRangeCsv = document.createElement("button");
    bRangeCsv.textContent = "Export range (CSV)";
    bRangeCsv.style.marginLeft = "8px";

    const bRangeJson = document.createElement("button");
    bRangeJson.textContent = "Export range (JSON)";
    bRangeJson.style.marginLeft = "8px";


  const bAllJson = document.createElement("button");
  bAllJson.textContent = "Export ALL pages (JSON)";
  bAllJson.style.marginLeft = "8px";

  const bAllCsv = document.createElement("button");
  bAllCsv.textContent = "Export ALL pages (CSV)";
  bAllCsv.style.marginLeft = "8px";

  const status = document.createElement("div");
  status.style.marginTop = "8px";
  status.style.fontSize = "12px";
  status.style.padding = "4px 6px";
  status.style.borderRadius = "4px";
  status.style.background = "#fff8dc";   // lighter than panel yellow
  status.style.color = "#222";           // force dark text for readability
  status.style.display = "inline-block";

  status.textContent = `Ready. Detected works on this page: ${getWorkItems().length}`;


  function setStatus(msg) {
    status.textContent = msg;
  }

  function setBusy(busy) {
    [bJson, bCsv, bAllJson, bAllCsv, bRangeJson, bRangeCsv].forEach(btn => {
      btn.disabled = busy;
    });
    startInput.disabled = busy;
    endInput.disabled = busy;
  }


  bAllJson.onclick = () => exportAllPages("json", setStatus, setBusy);
  bAllCsv.onclick = () => exportAllPages("csv", setStatus, setBusy);

  bRangeJson.onclick = () => {
    const s = parseInt(startInput.value, 10);
    const e = parseInt(endInput.value, 10);

    if (!Number.isFinite(s) || !Number.isFinite(e) || s < 1 || e < s) {
      setStatus("Invalid range. Start must be ≥ 1 and End ≥ Start.");
      return;
    }

    exportPageRange("json", s, e, setStatus, setBusy);
  };

  bRangeCsv.onclick = () => {
    const s = parseInt(startInput.value, 10);
    const e = parseInt(endInput.value, 10);

    if (!Number.isFinite(s) || !Number.isFinite(e) || s < 1 || e < s) {
      setStatus("Invalid range. Start must be ≥ 1 and End ≥ Start.");
      return;
    }

    exportPageRange("csv", s, e, setStatus, setBusy);
  };


  panel.appendChild(bJson);
  panel.appendChild(bCsv);
  panel.appendChild(bAllJson);
  panel.appendChild(bAllCsv);

  panel.appendChild(label);
  panel.appendChild(startInput);
  panel.appendChild(dash);
  panel.appendChild(endInput);
  panel.appendChild(bRangeJson);
  panel.appendChild(bRangeCsv);

  panel.appendChild(status);



  document.body.insertBefore(panel, document.body.firstChild);
})();
