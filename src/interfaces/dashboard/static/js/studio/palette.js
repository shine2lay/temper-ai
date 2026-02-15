/**
 * Palette - Left sidebar for the MAF Workflow Studio.
 *
 * Shows available configs (stages, agents, tools) organized by category,
 * supports text search/filter, section collapse, and HTML5 drag-and-drop
 * onto the canvas. Each section also includes a "+ New" button that
 * dispatches a custom event for the studio app to handle.
 *
 * Catalog data comes from ConfigStore (arrays of objects with at least
 * { name, description?, version? }).
 *
 * Drag payload:  application/json  ->  { type, name }
 *   type  : "stages" | "agents" | "tools"
 *   name  : the config name string
 */

import { ConfigStore } from './config-store.js';

// ── Section definitions (order matters for rendering) ──────────────
const SECTION_CONFIG = [
    { type: 'workflows', label: 'Workflows', icon: 'W', clickToLoad: true },
    { type: 'stages', label: 'Stages', icon: 'S' },
    { type: 'agents', label: 'Agents', icon: 'A' },
    { type: 'tools',  label: 'Tools',  icon: 'T' },
];

// HTML entity for the collapse toggle arrow
const TOGGLE_ARROW = '\u25BC';  // BLACK DOWN-POINTING TRIANGLE

export class Palette {
    /**
     * @param {ConfigStore} configStore  Shared store that owns catalog data.
     */
    constructor(configStore) {
        this._store = configStore;
        this._container = document.getElementById('palette-sections');
        this._searchInput = document.getElementById('palette-search-input');
        this._setupListeners();
        this._render();
    }

    // ── Lifecycle ──────────────────────────────────────────────────

    /** Wire up store and DOM events. */
    _setupListeners() {
        this._store.addEventListener('catalog-loaded', () => this._render());
        this._searchInput.addEventListener('input', () => this._applyFilter());
    }

    // ── Rendering ─────────────────────────────────────────────────

    /** Re-render every section from current catalog data. */
    _render() {
        this._container.innerHTML = '';
        for (const section of SECTION_CONFIG) {
            this._renderSection(section);
        }
        // Re-apply any active search filter after a re-render
        this._applyFilter();
    }

    /**
     * Build and append a single palette section (header + items + "New" button).
     * @param {{ type: string, label: string, icon: string }} sectionCfg
     */
    _renderSection(sectionCfg) {
        const items = this._store.catalogs[sectionCfg.type] || [];

        // Section wrapper
        const section = document.createElement('div');
        section.className = 'palette-section';
        section.dataset.type = sectionCfg.type;

        // ---- Header (click to collapse) ----
        const header = document.createElement('div');
        header.className = 'palette-section-header';

        const headerLabel = document.createElement('span');
        headerLabel.textContent = `${sectionCfg.label} (${items.length})`;

        const headerToggle = document.createElement('span');
        headerToggle.className = 'palette-section-toggle';
        headerToggle.textContent = TOGGLE_ARROW;

        header.appendChild(headerLabel);
        header.appendChild(headerToggle);
        header.addEventListener('click', () => {
            section.classList.toggle('collapsed');
        });
        section.appendChild(header);

        // ---- Items container ----
        const itemsContainer = document.createElement('div');
        itemsContainer.className = 'palette-items';

        for (const item of items) {
            const el = this._createPaletteItem(sectionCfg, item);
            itemsContainer.appendChild(el);
        }

        // ---- "+ New" button ----
        const singularLabel = sectionCfg.label.endsWith('s')
            ? sectionCfg.label.slice(0, -1)
            : sectionCfg.label;

        const newBtn = document.createElement('button');
        newBtn.className = 'studio-repeatable-add';
        newBtn.textContent = `+ New ${singularLabel}`;
        newBtn.addEventListener('click', () => {
            this._handleNewItem(sectionCfg.type);
        });
        itemsContainer.appendChild(newBtn);

        section.appendChild(itemsContainer);
        this._container.appendChild(section);
    }

    /**
     * Create a single draggable palette item element.
     *
     * @param {{ type: string, label: string, icon: string }} sectionCfg
     * @param {{ name: string, description?: string, version?: string }} item
     * @returns {HTMLElement}
     */
    _createPaletteItem(sectionCfg, item) {
        const itemName = typeof item === 'string' ? item : item.name;
        const itemDesc = typeof item === 'object' ? (item.description || '') : '';
        const typeSingular = sectionCfg.type.endsWith('s')
            ? sectionCfg.type.slice(0, -1)
            : sectionCfg.type;

        const el = document.createElement('div');
        el.className = `palette-item ${typeSingular}`;

        if (itemDesc) {
            el.title = itemDesc;
        }

        // Icon
        const iconSpan = document.createElement('span');
        iconSpan.className = 'palette-item-icon';
        iconSpan.textContent = sectionCfg.icon;

        // Label
        const labelSpan = document.createElement('span');
        labelSpan.className = 'palette-item-label';
        labelSpan.textContent = itemName;

        el.appendChild(iconSpan);
        el.appendChild(labelSpan);

        if (sectionCfg.clickToLoad) {
            // Click-to-load items (workflows): clicking imports into canvas
            el.style.cursor = 'pointer';
            el.addEventListener('click', () => {
                this._store.dispatchEvent(new CustomEvent('palette-load-workflow', {
                    detail: { name: itemName },
                }));
            });
        } else {
            // Draggable items (stages, agents, tools): HTML5 drag-and-drop
            el.draggable = true;
            el.addEventListener('dragstart', (e) => {
                const dragData = {
                    type: sectionCfg.type,
                    name: itemName,
                };
                e.dataTransfer.setData('application/json', JSON.stringify(dragData));
                e.dataTransfer.effectAllowed = 'copy';
                el.classList.add('dragging');
            });
            el.addEventListener('dragend', () => {
                el.classList.remove('dragging');
            });
        }

        return el;
    }

    // ── Search / Filter ───────────────────────────────────────────

    /**
     * Show/hide palette items based on the current search input value.
     * Also updates section header counts to reflect visible items,
     * and auto-expands sections that have matches while a query is active.
     */
    _applyFilter() {
        const query = this._searchInput.value.toLowerCase().trim();
        const sections = this._container.querySelectorAll('.palette-section');

        for (const section of sections) {
            const items = section.querySelectorAll('.palette-item');
            let visibleCount = 0;

            for (const item of items) {
                const label = item.querySelector('.palette-item-label');
                const matches = !query || label.textContent.toLowerCase().includes(query);
                item.style.display = matches ? '' : 'none';
                if (matches) {
                    visibleCount++;
                }
            }

            // Update the count in the section header
            const headerLabel = section.querySelector('.palette-section-header > span:first-child');
            if (headerLabel) {
                const totalCount = items.length;
                if (query && visibleCount !== totalCount) {
                    headerLabel.textContent = headerLabel.textContent.replace(
                        /\(\d+\)/,
                        `(${visibleCount}/${totalCount})`
                    );
                } else {
                    headerLabel.textContent = headerLabel.textContent.replace(
                        /\(\d+(?:\/\d+)?\)/,
                        `(${totalCount})`
                    );
                }
            }

            // Auto-expand sections with matches when searching
            if (query && visibleCount > 0) {
                section.classList.remove('collapsed');
            }
        }
    }

    // ── New Item ──────────────────────────────────────────────────

    /**
     * Dispatch a custom event so the studio app can open a creation dialog.
     * @param {string} type  One of "stages", "agents", "tools".
     */
    _handleNewItem(type) {
        this._store.dispatchEvent(new CustomEvent('palette-new-item', {
            detail: { type },
        }));
    }
}
