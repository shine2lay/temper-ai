/**
 * Client-side pub/sub event bus.
 * Provides a simple emit/on/off interface over EventTarget.
 */
export class ClientEventBus extends EventTarget {
    emit(eventType, data) {
        this.dispatchEvent(new CustomEvent(eventType, { detail: data }));
    }

    on(eventType, callback) {
        const handler = (e) => callback(e.detail);
        this.addEventListener(eventType, handler);
        return handler;
    }

    off(eventType, handler) {
        this.removeEventListener(eventType, handler);
    }
}
