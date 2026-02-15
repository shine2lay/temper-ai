/**
 * Panel registration and lifecycle management.
 * Panels are registered by class and bound to a container element.
 */
export class PanelRegistry {
    constructor(dataStore, eventBus) {
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this.panels = new Map();
    }

    register(PanelClass, containerId) {
        const container = document.getElementById(containerId);
        if (!container) {
            console.warn(`Container #${containerId} not found`);
            return;
        }
        const contentEl = container.querySelector('.panel-content') || container;
        const panel = new PanelClass(contentEl, this.dataStore, this.eventBus);
        this.panels.set(PanelClass.metadata?.id || containerId, panel);
        return panel;
    }

    destroyAll() {
        for (const panel of this.panels.values()) {
            if (panel.destroy) panel.destroy();
        }
        this.panels.clear();
    }
}
