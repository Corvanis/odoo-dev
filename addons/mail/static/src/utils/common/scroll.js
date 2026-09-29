import { useLayoutEffect } from "@web/owl2/utils";
import { useVisible } from "@mail/utils/common/hooks";

import { onMounted, onPatched, onWillPatch, proxy, signal, untrack } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

export const JUMP_TO_END_VIEWPORT_THRESHOLD = 1;

/**
 * Stored scroll position of a list: either `"bottom"` when at the end of the
 * list (optionally `"bottom-smooth"` to reach it with a smooth scroll), or the
 * distance in pixels from the start of the list.
 *
 * @typedef {number|"bottom"|"bottom-smooth"|undefined} ScrollPosition
 */

/**
 * Item to scroll to, taking precedence over any other scroll: either the key
 * of an item to center, or the end of the list.
 *
 * @typedef {{ key: any }|{ end: true }} ScrollTarget
 */

/**
 * @param {ScrollPosition} position
 */
function isEndPosition(position) {
    return typeof position === "string" && position.includes("bottom");
}

/**
 * @returns {Promise<void>} resolved once the ongoing scroll ends.
 */
export function waitForScrollEnd() {
    const { promise, resolve } = Promise.withResolvers();
    if ("onscrollend" in window) {
        document.addEventListener("scrollend", () => resolve(), { capture: true, once: true });
    } else {
        // To remove when safari will support the "scrollend" event.
        browser.setTimeout(resolve, 250);
    }
    return promise;
}

/**
 * @typedef {Object} ScrollManagerParams
 * @property {import("@odoo/owl").ReactiveValue<HTMLElement>} ref the element
 *  with the scrollbar.
 * @property {() => boolean} [reversed] whether the end of the list is displayed
 *  at the top.
 * @property {() => boolean} ready whether the items are displayed. The scroll
 *  is only applied when ready.
 * @property {() => { start: number, end: number }} bounds keys of the first
 *  and last items, increasing from start to end (e.g. record ids). Used to
 *  detect items added at either end of the list.
 * @property {() => boolean} [hasMoreAfterEnd] whether more items can be loaded
 *  after the last one, in which case the list is never considered at its end.
 * @property {() => ScrollPosition} getPosition
 * @property {(position: ScrollPosition) => void} setPosition
 * @property {(key: any) => HTMLElement|undefined} getItemEl element of the item
 *  with the given key, if rendered.
 * @property {(itemEl: HTMLElement) => HTMLElement} [getItemScrollTarget] element
 *  to scroll into view to reveal the given item element.
 * @property {(end: number) => any} [getFirstItemAfter] key of the item to
 *  scroll to, rather than scrolling to the end, when items are added after
 *  `end` while at the end of the list.
 * @property {() => ScrollTarget|undefined} [getTarget]
 * @property {(target: ScrollTarget) => void} [onTargetReached]
 * @property {() => boolean} [paused] whether restoring the stored position is
 *  paused, for instance to give priority to another scroll.
 * @property {() => void} onNotReady called when the scroll cannot be applied
 *  because the items are not displayed. The owner is expected to reset its
 *  state, including this scroll with `reset()`.
 * @property {() => void} [onFirstApply] called when the scroll is applied for
 *  the first time since the last reset.
 * @property {() => void} [onScroll] called when the scrollable element scrolls.
 */

/**
 * Manages the scroll of a list whose items can be added at both ends.
 *
 * 1. A target (@see ScrollTarget) takes precedence over anything else.
 * 2. When items are added at either end, the items already on screen should
 *    visually stay in place. When the extra items are added at the bottom the
 *    same scroll top position should be kept, and when they are added at the
 *    top, their extra height should be compensated in the scroll position.
 * 3. When the scroll is at the end, it should stay at the end when there is a
 *    change of height: new items, images loaded, ...
 * 4. The scroll position is stored with `setPosition` and restored from
 *    `getPosition`, which allows to restore the last position of a list when
 *    going back and forth between lists.
 * 5. Restoring the position is skipped while `paused`, for instance when an
 *    item is being revealed.
 */
export class ScrollManager {
    /**
     * Last scroll value that was automatically set. This prevents from
     * setting the same value 2 times in a row. This is not supposed to have
     * an effect, unless the value was changed from outside in the meantime,
     * in which case resetting the value would incorrectly override the
     * other change. This should give enough time to scroll/resize event to
     * register the new scroll value.
     */
    lastSetValue = undefined;
    /**
     * The snapshot mechanism (point 2) should only apply after the items have
     * been displayed at least once. Technically this is after the first patch
     * following when `ready` is true. This is what this variable holds.
     */
    initialized = false;
    /**
     * The snapshot of current scrollTop and scrollHeight for the purpose
     * of keeping items in place when adding items (point 2).
     */
    snapshot = undefined;
    /**
     * The bounds of the items that are already rendered, useful to detect
     * whether items have been added since last render to decide when to apply
     * the snapshot to keep items in place (point 2).
     *
     * @type {{ start: number, end: number }|undefined}
     */
    bounds = undefined;
    /**
     * Whether it was possible to load more items after the end in the last
     * rendered state, useful to decide when to apply the snapshot to keep items
     * in place (point 2).
     */
    hadMoreAfterEnd = false;
    /** @type {Promise|undefined} */
    smoothScrollingPromise;
    /** @type {Promise|undefined} */
    revealPromise;

    /**
     * @param {ScrollManagerParams} params
     */
    constructor(params) {
        this.params = params;
        this.ref = params.ref;
        this.revealRequest = signal(null);
        this.apply = this.apply.bind(this);
        this.onScroll = this.onScroll.bind(this);
        useLayoutEffect(
            (request, itemEl) => {
                if (request && itemEl) {
                    this.apply();
                }
            },
            () => {
                const request = this.revealRequest();
                return [request, request && this.params.getItemEl(request.key)];
            }
        );
        onWillPatch(() => {
            if (!this.initialized) {
                return;
            }
            this.snapshot = {
                scrollHeight: this.ref().scrollHeight,
                scrollTop: this.ref().scrollTop,
            };
        });
        onMounted(this.apply);
        onPatched(this.apply);
        const observer = new ResizeObserver(() => this.apply());
        useLayoutEffect(
            (el, ready) => {
                if (el && ready) {
                    el.addEventListener("scroll", this.onScroll);
                    observer.observe(el);
                    return () => {
                        observer.unobserve(el);
                        el.removeEventListener("scroll", this.onScroll);
                    };
                }
            },
            () => [this.ref(), this.params.ready()]
        );
    }

    get reversed() {
        return this.params.reversed?.() ?? false;
    }

    get isAtEnd() {
        if (this.hadMoreAfterEnd) {
            return false;
        }
        const el = this.ref();
        return this.reversed
            ? el.scrollTop < 30
            : el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    }

    get isSmoothScrolling() {
        return Boolean(this.smoothScrollingPromise);
    }

    /**
     * Scroll top value of the end of the list.
     */
    get endScrollTop() {
        return this.reversed ? 0 : this.ref().scrollHeight - this.ref().clientHeight;
    }

    apply() {
        if (!this.params.ready()) {
            this.params.onNotReady();
            return;
        }
        if (!this.applyContextually()) {
            return;
        }
        this.snapshot = undefined;
        this.bounds = this.params.bounds();
        this.hadMoreAfterEnd = this.params.hasMoreAfterEnd?.() ?? false;
        if (!this.initialized) {
            this.initialized = true;
            this.params.onFirstApply?.();
        }
        // After the scroll is applied, so that it doesn't override the reveal.
        const request = this.revealRequest();
        const itemEl = request && this.params.getItemEl(request.key);
        if (itemEl) {
            this.revealItem(itemEl, request);
        }
    }

    /**
     * @returns {Boolean} true when the scroll is applied, false when the items
     *  to scroll to are not rendered yet.
     */
    applyContextually() {
        const target = this.params.getTarget?.();
        if (target) {
            return this.applyTarget(target);
        }
        const el = this.ref();
        const bounds = this.params.bounds();
        const position = this.params.getPosition();
        const addedBefore = bounds.start < this.bounds?.start;
        const addedAfter = bounds.end > this.bounds?.end;
        const addedAtTop = this.reversed ? addedAfter : addedBefore;
        const addedAtBottom = this.reversed
            ? addedBefore
            : addedAfter && (this.hadMoreAfterEnd || !isEndPosition(position));
        if (this.snapshot && addedAtTop) {
            this.set(this.snapshot.scrollTop + el.scrollHeight - this.snapshot.scrollHeight);
        } else if (this.snapshot && addedAtBottom) {
            this.set(this.snapshot.scrollTop);
        } else if (!this.params.paused?.() && position !== undefined) {
            let value;
            if (isEndPosition(position)) {
                const key = addedAfter
                    ? this.params.getFirstItemAfter?.(this.bounds.end)
                    : undefined;
                if (key !== undefined) {
                    const itemEl = this.params.getItemEl(key);
                    if (!itemEl) {
                        return false;
                    }
                    this.getItemScrollTarget(itemEl).scrollIntoView({
                        behavior: "instant",
                        block: this.reversed ? "end" : "start",
                    });
                    this.save();
                    return true;
                }
                value = this.endScrollTop;
            } else {
                value = this.reversed ? el.scrollHeight - position - el.clientHeight : position;
            }
            if (
                (this.lastSetValue === undefined || Math.abs(this.lastSetValue - value) > 1) &&
                !this.isSmoothScrolling
            ) {
                this.set(value, {
                    smooth: typeof position === "string" && position.includes("smooth"),
                });
            }
        }
        return true;
    }

    /**
     * @param {ScrollTarget} target
     * @returns {Boolean} true when the scroll is applied, false when the item
     *  to scroll to is not rendered yet.
     */
    applyTarget(target) {
        if (target.end) {
            this.set(this.endScrollTop);
        } else {
            const itemEl = this.params.getItemEl(target.key);
            if (!itemEl) {
                return false;
            }
            this.set(itemEl.offsetTop - this.ref().offsetHeight / 2 + itemEl.offsetHeight / 2);
        }
        this.params.onTargetReached?.(target);
        return true;
    }

    /**
     * @param {HTMLElement} itemEl
     */
    getItemScrollTarget(itemEl) {
        return this.params.getItemScrollTarget?.(itemEl) ?? itemEl;
    }

    onScroll() {
        this.params.onScroll?.();
        this.save();
    }

    reset() {
        this.lastSetValue = undefined;
        this.snapshot = undefined;
        this.bounds = undefined;
        this.initialized = false;
        this.hadMoreAfterEnd = false;
    }

    /**
     * Smoothly scrolls to the item with the given key, as soon as it is
     * rendered and the scroll is applied.
     *
     * @param {any} key
     * @param {Object} [options]
     * @param {boolean} [options.fromEnd=false] whether to jump to the end of the
     *  list before scrolling to the item.
     */
    reveal(key, { fromEnd = false } = {}) {
        this.revealRequest.set({ key, fromEnd });
    }

    /**
     * @param {HTMLElement} itemEl
     * @param {{ fromEnd: boolean }} request
     */
    async revealItem(itemEl, { fromEnd }) {
        this.revealRequest.set(null);
        const { promise, resolve } = Promise.withResolvers();
        this.revealPromise = promise;
        promise.then(() => {
            if (this.revealPromise === promise) {
                this.revealPromise = undefined;
            }
        });
        if (fromEnd) {
            this.set(this.endScrollTop);
            // Let the jump to the end complete, so that its "scrollend" event
            // is not mistaken for the end of the reveal.
            await new Promise((resolve) => browser.requestAnimationFrame(resolve));
        } else {
            // the stored position is outdated by the reveal
            this.params.setPosition(undefined);
        }
        waitForScrollEnd().then(resolve);
        this.getItemScrollTarget(itemEl).scrollIntoView({ behavior: "smooth", block: "center" });
    }

    save() {
        const el = this.ref();
        if (this.isAtEnd) {
            this.params.setPosition("bottom");
        } else {
            this.params.setPosition(
                this.reversed ? el.scrollHeight - el.scrollTop - el.clientHeight : el.scrollTop
            );
        }
    }

    set(value, { smooth = false } = {}) {
        if (smooth) {
            const promise = waitForScrollEnd();
            this.smoothScrollingPromise = promise;
            promise.then(() => {
                if (this.smoothScrollingPromise === promise) {
                    this.smoothScrollingPromise = undefined;
                }
            });
        }
        this.ref().scrollTo({ behavior: smooth ? "smooth" : undefined, top: value });
        this.lastSetValue = value;
        this.save();
    }

    /**
     * @returns {Promise} resolved once the ongoing reveal and smooth scroll, if
     *  any, are done.
     */
    waitForIdle() {
        return Promise.all([this.revealPromise, this.smoothScrollingPromise]);
    }
}

/**
 * @param {ScrollManagerParams} params
 * @returns {ScrollManager}
 */
export function useScrollManager(params) {
    return new ScrollManager(params);
}

/**
 * @typedef {Object} JumpToEndButtonParams
 * @property {import("@odoo/owl").Signal<HTMLElement>} rootRef the element whose
 *  visibility conditions the display of the button.
 * @property {import("@odoo/owl").ReactiveValue<HTMLElement>} scrollableRef the
 *  element with the scrollbar.
 * @property {() => boolean} [hasMoreAfterEnd] whether more items can be loaded
 *  after the last one, in which case the button is shown.
 * @property {() => boolean} ready whether the items are displayed.
 * @property {(size: { width: number, height: number }) => { x: number, y: number }} position
 *  translation of the button given the inner size of the viewport.
 */

/**
 * Tracks whether the scroll is far enough from the end of a list to show a
 * "jump to end" button, and keeps the button positioned in the viewport. The
 * `thresholdRef` element should span the height beyond which the button is
 * shown (`threshold`), from the end of the list.
 */
export class JumpToEndButton {
    /**
     * @param {JumpToEndButtonParams} params
     */
    constructor(params) {
        this.params = params;
        this.scrollableRef = params.scrollableRef;
        this.ref = signal.ref();
        this.thresholdRef = signal.ref();
        this.state = proxy({ show: false });
        this.rootVisibleState = useVisible(params.rootRef, () => this.update());
        this.thresholdState = useVisible(this.thresholdRef, () => this.update());
        useLayoutEffect(
            () => {
                this.computePosition();
            },
            () => [untrack(this.ref), untrack(() => this.viewportEl)]
        );
        useLayoutEffect(
            () => this.update(),
            () => [this.params.hasMoreAfterEnd?.()]
        );
        useLayoutEffect(
            (ready) => {
                if (ready) {
                    this.update();
                }
            },
            () => [this.params.ready()]
        );
        const observer = new ResizeObserver(() => this.computePosition());
        useLayoutEffect(
            (el, ready) => {
                if (el && ready) {
                    observer.observe(el);
                    return () => observer.unobserve(el);
                }
            },
            () => [this.scrollableRef(), this.params.ready()]
        );
    }

    /**
     * Height, from the end of the list, beyond which the button is shown.
     */
    get threshold() {
        const threshold = (this.viewportEl?.clientHeight ?? 0) * JUMP_TO_END_VIEWPORT_THRESHOLD;
        return this.state.show ? threshold - 200 : threshold;
    }

    get viewportEl() {
        let viewportEl = this.scrollableRef();
        if (viewportEl && viewportEl.clientHeight > browser.innerHeight) {
            while (viewportEl && viewportEl.clientHeight > browser.innerHeight) {
                viewportEl = viewportEl.parentElement;
            }
        }
        return viewportEl;
    }

    computePosition() {
        const viewportEl = this.viewportEl;
        if (!viewportEl || !this.ref()) {
            return;
        }
        const computedStyle = window.getComputedStyle(viewportEl);
        const ps = parseInt(computedStyle.getPropertyValue("padding-left"));
        const pe = parseInt(computedStyle.getPropertyValue("padding-right"));
        const pt = parseInt(computedStyle.getPropertyValue("padding-top"));
        const pb = parseInt(computedStyle.getPropertyValue("padding-bottom"));
        const { x, y } = this.params.position({
            width: viewportEl.clientWidth - ps - pe,
            height: viewportEl.clientHeight - pt - pb,
        });
        this.ref().style.transform = `translate(${x}px, ${y}px)`;
    }

    update() {
        this.state.show =
            this.rootVisibleState.isVisible &&
            (this.params.hasMoreAfterEnd?.() || this.thresholdState.isVisible === false);
    }
}

/**
 * @param {JumpToEndButtonParams} params
 * @returns {JumpToEndButton}
 */
export function useJumpToEndButton(params) {
    return new JumpToEndButton(params);
}
