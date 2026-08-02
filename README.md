# IMGMT-annot-webapp

The web application to manually annotate or post-edit pairs of SVGs with text that are supposed to be each other's translations. The annotation is stored in a JSON and contains all bounding boxes representing text fields, their text content, and alignment of the text fields between the SVGs.

---

## Features

- **Simple ID-based login** — enter a User ID; the app loads that user's pre-assigned SVG/JSON pairs.
- **Side-by-side SVG view** using interactive [Fabric.js](http://fabricjs.com/) canvases with pan and zoom.
- **Bounding Box Correction tab**
  - Sidebar listing all annotated text fields for SVG A and SVG B.
  - English translations for non-English labels are available in each label's tooltip.
  - Click a list item to highlight the corresponding bounding box on the canvas.
  - Double-click to open an edit modal (change text, coordinates, size, or delete the box).
  - Draw new bounding boxes directly on the canvas (`+A` / `+B` buttons).
  - Click anywhere on the canvas to get a **popup list** of all boxes that overlap the clicked point (select, edit, or delete).
- **Alignment Mapping tab**
  - Sidebar listing every A↔B text-field alignment.
  - Click an alignment to highlight both boxes at once.
  - Add new alignments or delete existing ones.
- **Auto-save** — every change is debounced and written back to the JSON file on the server within ~800 ms.
- **Comments** — add free-form comments to each SVG and to the pair from their corresponding panes.

---

## Project Structure

```
IMGMT-annot-webapp/
├── main.py                  # FastAPI backend
├── requirements.txt         # Python dependencies
├── frontend/
│   └── index.html           # Single-page frontend (HTML + Tailwind + Fabric.js)
└── data/
    ├── users.json           # User → dataset partition mapping
    └── datasets/
        ├── demo_user/
        │   ├── pair_001/
        │   │   ├── svgA.svg
        │   │   ├── svgB.svg
        │   │   └── annotations.json
        │   └── pair_002/
        │       ├── svgA.svg
        │       ├── svgB.svg
        │       └── annotations.json
        └── annotator1/
            └── pair_001/
                ├── svgA.svg
                ├── svgB.svg
                └── annotations.json
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the server

```bash
python main.py [DATA_DIR]
```

`DATA_DIR` is the directory containing `users.json`, `bbs/`, and `pairs/`.
When omitted, the bundled `data/` directory is used. For example:

```bash
python main.py /path/to/my-data
```

### 3. Open the app

Navigate to **http://localhost:8000** in your browser.

### 4. Log in

Use one of the pre-configured User IDs:

| User ID      | Assigned pairs           |
|-------------|--------------------------|
| `demo_user`  | `pair_001`, `pair_002`   |
| `annotator1` | `pair_001`               |

---

## Adding Your Own Data

### Add a new user

Edit `data/users.json`:

```json
{
  "alice": {
    "display_name": "Alice",
    "datasets": ["pair_001", "pair_003"]
  }
}
```

### Add a new SVG/JSON pair for a user

Create the folder `data/datasets/<user_id>/<pair_id>/` and place:

- `svgA.svg` — source SVG
- `svgB.svg` — translation SVG
- `annotations.json` — annotation data (see format below)

The folder name must match the entry in `users.json`.

### Annotation JSON format

```json
{
  "svgA": {
    "comment": "",
    "boxes": [
      { "id": "A1", "x": 10, "y": 20, "width": 150, "height": 25, "text": "Hello" }
    ]
  },
  "svgB": {
    "comment": "",
    "boxes": [
      { "id": "B1", "x": 12, "y": 22, "width": 140, "height": 24, "text": "Hallo" }
    ]
  },
  "alignments": [
    { "boxA": "A1", "boxB": "B1" }
  ],
  "comment": ""
}
```

If a pair directory has no `annotations.json`, the app starts with an empty annotation skeleton.

### Sort bounding boxes

Bounding boxes can be sorted in an existing, partially annotated batch without
changing their IDs. Alignment pairs are reordered to match the resulting
top-to-bottom, left-to-right order of the SVG A bounding boxes:

```bash
python utils/sort_bbs.py /path/to/my-data
```

To sort only the pairs assigned to one user, pass the user ID. Shared BB files
referenced by multiple assigned pairs are sorted only once:

```bash
python utils/sort_bbs.py /path/to/my-data --user annotator1
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/api/login/{user_id}` | Validate user and return assigned pairs |
| `GET`  | `/api/users` | List all known users |
| `GET`  | `/api/users/{user_id}/pairs` | List pairs for a user |
| `GET`  | `/api/users/{user_id}/pairs/{pair_id}/svg/{side}` | Serve SVG (`side` = `A` or `B`) |
| `GET`  | `/api/users/{user_id}/pairs/{pair_id}/annotations` | Fetch annotation JSON |
| `PUT`  | `/api/users/{user_id}/pairs/{pair_id}/annotations` | Save annotation JSON |
| `POST` | `/api/translate` | Translate labels to English and detect their source language |

Interactive API docs are available at **http://localhost:8000/docs**.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Escape` | Cancel drawing / close popup or modal |
| `Delete` / `Backspace` | Delete the currently selected bounding box on the canvas |
| `ArrowUp` / `ArrowDown` | In the active pane, select the previous / next alignment or bounding box |
| `ArrowLeft` / `ArrowRight` | In the BB pane, move focus between the SVG A and SVG B bounding-box columns |
| Mouse wheel | Zoom in / out on canvases |
| `Alt` + drag | Pan canvas |

---

## Tech Stack

- **Backend:** Python 3.10+, [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/)
- **Frontend:** HTML5, [Tailwind CSS](https://tailwindcss.com/) (CDN), [Fabric.js](http://fabricjs.com/) (CDN), vanilla JavaScript
