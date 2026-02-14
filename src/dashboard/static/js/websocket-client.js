/**
 * WebSocket client with auto-reconnect and exponential backoff.
 * Connects to /ws/{workflowId} and feeds events into DataStore.
 */
export class WebSocketClient {
    constructor(workflowId, dataStore) {
        this.workflowId = workflowId;
        this.dataStore = dataStore;
        this.ws = null;
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 30000;
        this.connected = false;
        this.onStatusChange = null;
    }

    connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/ws/${this.workflowId}`;

        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            this.connected = true;
            this.reconnectDelay = 1000;
            if (this.onStatusChange) this.onStatusChange(true);
        };

        this.ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'snapshot') {
                this.dataStore.applySnapshot(msg.workflow);
            } else if (msg.type === 'event') {
                this.dataStore.applyEvent(msg);
            }
            // heartbeat messages are silently accepted
        };

        this.ws.onclose = () => {
            this.connected = false;
            if (this.onStatusChange) this.onStatusChange(false);
            this._reconnect();
        };

        this.ws.onerror = () => {
            // Error will trigger onclose
        };
    }

    disconnect() {
        if (this.ws) {
            this.ws.onclose = null;
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
    }

    _reconnect() {
        setTimeout(() => {
            this.connect();
            this.reconnectDelay = Math.min(
                this.reconnectDelay * 2,
                this.maxReconnectDelay
            );
        }, this.reconnectDelay);
    }
}
