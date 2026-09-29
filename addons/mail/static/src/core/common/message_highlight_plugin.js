import { onWillDestroy, Plugin, proxy, t, useConfig } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/**
 * Highlights a message of the thread given in config, loading the messages
 * around it when needed. Components displaying the thread react to the
 * highlighted message, for instance by scrolling to it.
 *
 * Config:
 * - `thread`: function returning the thread whose messages are highlighted.
 * - `messageFetchRouteParams` (optional): function returning the route
 *   params used to load the messages around the highlighted message.
 */
export class MessageHighlightPlugin extends Plugin {
    duration = 1500;
    /** @type {() => import("models").Thread|null} */
    thread = useConfig("thread", t.function());
    /** @type {(() => Object)|undefined} */
    messageFetchRouteParams = useConfig("messageFetchRouteParams", t.function().optional());
    state = proxy({
        /** @type {number|null} */
        highlightedMessageId: null,
        /**
         * Whether the highlighted message is older than the messages that were
         * loaded when it was highlighted.
         */
        isOlderThanLoaded: false,
    });
    /** @type {number|null} */
    timeout = null;

    setup() {
        onWillDestroy(() => browser.clearTimeout(this.timeout));
    }

    get highlightedMessageId() {
        return this.state.highlightedMessageId;
    }

    set highlightedMessageId(messageId) {
        this.state.highlightedMessageId = messageId;
    }

    get isOlderThanLoaded() {
        return this.state.isOlderThanLoaded;
    }

    clear() {
        if (this.highlightedMessageId) {
            browser.clearTimeout(this.timeout);
            this.timeout = null;
            this.highlightedMessageId = null;
            this.state.isOlderThanLoaded = false;
        }
    }

    /**
     * @param {import("models").Message} message
     */
    async highlightMessage(message) {
        const thread = this.thread();
        if (!thread) {
            return;
        }
        let isOlderThanLoaded = false;
        if (message.notIn(thread.messages)) {
            isOlderThanLoaded = message.id < thread.messages[0]?.id;
            await thread.loadAround({
                messageId: message.id,
                routeParams: this.messageFetchRouteParams ? this.messageFetchRouteParams() : {},
            });
        }
        const lastHighlightedMessageId = this.highlightedMessageId;
        this.clear();
        if (lastHighlightedMessageId === message.id) {
            // Give some time for the state to update.
            await new Promise(setTimeout);
        }
        this.state.isOlderThanLoaded = isOlderThanLoaded;
        this.highlightedMessageId = message.id;
        this.timeout = browser.setTimeout(() => this.clear(), this.duration);
    }
}
