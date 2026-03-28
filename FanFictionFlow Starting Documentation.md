# FanFictionFlow

## Purpose

To streamline the process of transferring AO3 fan fiction between devices and maintaining metadata.

## History

Currently have developed some small tools and processes to manage the process (see Fan Fiction Workflow). These tools were developed with ChatGPT.

## Fan Fiction Workflow

Current steps:

- Periodically add new stories using Mark for Later on AO3
- In Calibre Browser app on Boox Palma, Export Status
- Use command prompt to update #readstatus to Calibre library (match on Calibre id)
- Manually open every updated story on AO3 and Mark as Read
- Add any new favorites to AO3 bookmarks
- Pull csv from Marked for Later list using Chrome extension
- Export existing FanFiction library from Calibre
- XLOOKUP between spreadsheets based on work_id
- Filter to stories that do not yet exist in Calibre
- Create links in spreadsheet by concatenating URL with work_id
- Open story pages and download epub files
- Import epub files into Calibre
- Export updated FanFiction library from Calibre
- Clean up metadata in Marked for Later csv (Collection, Primary Ship)
- XLOOKUP between updated library and metadata file to add the work_id
- Use command prompt to add metadata to Calibre library based on work_id
- Transfer epub files to Boox Palma
- Export another new Fanfiction library from Calibre
- Save library file to Boox Palma
- Import library file to AO3 Read Status Badge Chrome extension

---

## Component Details

### AO3 Readings To-Read Exporter

The AO3 metadata export script is a custom Tampermonkey userscript designed to extract structured work data directly from Archive of Our Own (Archive of Our Own) listing pages such as History and Marked for Later. The script injects client-side JavaScript into AO3 pages, traverses the DOM to identify individual work entries, and parses key metadata fields including title, author(s), fandom(s), relationship tags, word count, and work ID. It normalizes and cleans this data in-browser, handling edge cases such as multiple tag formats, inconsistent delimiters, and embedded commas. The extracted data is then compiled into a structured dataset and exported as a downloadable CSV or JSON file, preserving the AO3 work ID as a primary key for downstream integration. This output is specifically formatted to align with a Calibre ingestion workflow, enabling bulk import, metadata enrichment, and subsequent synchronization with external tools such as the Calibre Browser app.

### AO3 Read Status Badge

This browser extension enhances the AO3 (Archive of Our Own) user interface by integrating external reading status data sourced from a Calibre-exported CSV file. The extension allows the user to upload a CSV containing #ao3_work_id and #readstatus fields, which are parsed and stored locally as a key-value mapping of work ID to read status. A content script runs on AO3 pages, extracting work IDs from both individual work URLs and listing page elements, and cross-references them against the stored dataset. It then injects a visual badge adjacent to each work title indicating the corresponding read status (e.g., Read, In Progress, DNF), defaulting to “Unread” when no match is found. All data processing and storage occur client-side using browser extension storage APIs, requiring no external services. This provides a persistent, non-invasive overlay that augments AO3 browsing with user-specific reading state information derived from their Calibre library.

### Calibre Browser Android App

The Calibre Browser app is an Android-based utility designed to provide a streamlined, metadata-driven interface for browsing and managing a personal ebook library exported from Calibre. It ingests a CSV catalog containing structured metadata (including unique Calibre IDs, titles, authors, collections, relationship tags, word counts, and read status) and constructs an in-memory list of book records for filtering and display. In parallel, the app scans a user-selected directory of EPUB files and builds an index by parsing filenames to extract the leading Calibre ID (e.g., 12345 - Title.epub), creating a mapping of ID to file URI. This allows the app to resolve each catalog entry to its corresponding local file for direct opening via Android intents. Users can filter and sort the library across multiple dimensions, including collection, primary relationship, word count ranges, and read status. The app also implements a device-level read status override system using Android DataStore, where user changes are stored as key-value pairs keyed by book ID. These overrides are merged with the catalog at runtime and can be exported as a minimal CSV containing only modified statuses, enabling efficient synchronization back to external systems such as Calibre.

#### Status Export

This system implements a structured workflow for synchronizing reading metadata between an Android-based browsing interface and a local Calibre library. The Android application exports user-defined read status updates as a CSV file containing Calibre record IDs and corresponding status values, which is then processed via a PowerShell automation script. Using the calibredb CLI, the script performs batch updates to a custom #readstatus column and simultaneously updates the built-in timestamp field to reflect the modification date. This approach enables efficient, repeatable, and large-scale metadata management without manual interaction in the Calibre GUI, while maintaining a clear audit trail of changes and supporting integration with additional automation processes such as AO3 work ID extraction.

#### Calibre Updates

Metadata updates to the Calibre fan fiction library were automated using a PowerShell-driven workflow that leverages the calibredb command-line interface. Source data was prepared in structured CSV files containing Calibre book IDs and target custom column values (e.g., #collection, #primaryship, #wordcount, #readstatus, #ao3_work_id). The script iterates over each row, using the Calibre-specific ID as a deterministic key to directly update only the intended records via set_custom, avoiding any need for fuzzy matching or full-database scans. Each update operation invokes calibredb with the appropriate column identifier and value, ensuring precise, repeatable writes to the SQLite-backed library. This approach enables efficient batch updates, supports multiple targeted update passes (e.g., metadata normalization, read status, AO3 ID enrichment), and maintains data integrity by isolating changes to explicitly defined records.

### Calibre App

Calibre (https://calibre-ebook.com/) is an open-source, cross-platform e-book management application designed to serve as a centralized system for organizing, converting, and delivering digital reading content. It maintains a structured local library backed by a metadata database, allowing users to store, edit, and search extensive book details such as authors, tags, series, and custom fields. The application supports a wide range of e-book formats and includes robust conversion pipelines to normalize files for compatibility across devices. Calibre also provides device synchronization, automated news fetching, and a built-in content server with OPDS support, enabling remote access to the library through web browsers and reading apps. Its extensible plugin architecture and command-line utilities make it highly adaptable for advanced workflows, including batch metadata updates and integration with external tools.