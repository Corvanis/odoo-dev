const DOW_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

function joinClasses(...classes) {
    return classes.flat().filter(Boolean).join(" ");
}

function dateClasses(info) {
    return [
        "fc-day",
        `fc-day-${DOW_NAMES[info.dow]}`,
        info.isToday && "fc-day-today",
        info.isPast && "fc-day-past",
        info.isFuture && "fc-day-future",
        info.isOther && "fc-day-other",
        info.isDisabled && "fc-day-disabled",
    ];
}

function eventRangeClasses(info) {
    return [
        info.isStart && "fc-event-start",
        info.isEnd && "fc-event-end",
        info.isPast && "fc-event-past",
        info.isFuture && "fc-event-future",
        info.isToday && "fc-event-today",
    ];
}

function eventClasses(info) {
    return [
        "fc-event",
        ...eventRangeClasses(info),
        info.isMirror && "fc-event-mirror",
        info.isDragging && "fc-event-dragging",
        info.isResizing && "fc-event-resizing",
        info.isSelected && "fc-event-selected",
        info.isDraggable && "fc-event-draggable",
        (info.isStartResizable || info.isEndResizable) && "fc-event-resizable",
    ];
}

/**
 * FullCalendar v7 no longer exposes stable class names (its own classes are hashed) nor ships a
 * default theme. These generators restore the v6 semantic class names we style and query.
 */
const COMPAT_CLASSES = {
    className: "fc",
    viewClass: (info) => ["fc-view", `fc-${info.view.type}-view`],
    dayHeaderClass: (info) => [...dateClasses(info), "fc-col-header-cell"],
    dayHeaderInnerClass: "fc-col-header-cell-cushion",
    dayHeaderRowClass: "fc-col-header-row",
    dayCellClass: (info) => [...dateClasses(info), "fc-daygrid-day"],
    dayCellTopClass: "fc-daygrid-day-top",
    dayCellTopInnerClass: "fc-daygrid-day-number",
    dayCellInnerClass: "fc-daygrid-day-events",
    dayCellBottomClass: "fc-daygrid-day-bottom",
    dayLaneClass: (info) => [...dateClasses(info), "fc-timegrid-col"],
    dayLaneInnerClass: "fc-timegrid-col-events",
    slotLaneClass: (info) => [
        "fc-timegrid-slot",
        "fc-timegrid-slot-lane",
        info.isMinor && "fc-timegrid-slot-minor",
    ],
    slotHeaderClass: (info) => [
        "fc-timegrid-slot",
        "fc-timegrid-slot-label",
        info.isMinor && "fc-timegrid-slot-minor",
    ],
    slotHeaderInnerClass: "fc-timegrid-slot-label-cushion",
    allDayHeaderClass: "fc-timegrid-axis",
    allDayHeaderInnerClass: "fc-timegrid-axis-cushion",
    weekNumberHeaderClass: "fc-timegrid-axis fc-week-number",
    weekNumberHeaderInnerClass: "fc-timegrid-axis-cushion",
    allDayDividerClass: "fc-timegrid-divider",
    inlineWeekNumberClass: "fc-daygrid-week-number",
    eventClass: eventClasses,
    eventInnerClass: "fc-event-main",
    eventTimeClass: "fc-event-time",
    eventTitleClass: "fc-event-title",
    rowEventClass: "fc-daygrid-event fc-daygrid-block-event",
    columnEventClass: "fc-timegrid-event",
    listItemEventClass: "fc-daygrid-event fc-daygrid-dot-event",
    listItemEventBeforeClass: "fc-daygrid-event-dot",
    rowEventBeforeClass: (info) =>
        info.isStartResizable && "fc-event-resizer fc-event-resizer-start",
    rowEventAfterClass: (info) => info.isEndResizable && "fc-event-resizer fc-event-resizer-end",
    columnEventBeforeClass: (info) =>
        info.isStartResizable && "fc-event-resizer fc-event-resizer-start",
    columnEventAfterClass: (info) => info.isEndResizable && "fc-event-resizer fc-event-resizer-end",
    backgroundEventClass: (info) => ["fc-bg-event", ...eventRangeClasses(info)],
    moreLinkClass: "fc-more-link",
    rowMoreLinkClass: "fc-daygrid-more-link",
    columnMoreLinkClass: "fc-timegrid-more-link",
    nowIndicatorHeaderClass: "fc-timegrid-now-indicator-arrow",
    nowIndicatorLineClass: "fc-timegrid-now-indicator-line",
    toolbarClass: "fc-toolbar fc-header-toolbar",
    toolbarSectionClass: "fc-toolbar-chunk",
    toolbarTitleClass: "fc-toolbar-title",
    popoverClass: "fc-popover fc-more-popover",
    popoverCloseClass: "fc-popover-close",
    highlightClass: "fc-highlight",
    nonBusinessHoursClass: "fc-non-business",
    tableHeaderClass: "fc-scrollgrid-section-header",
    tableBodyClass: "fc-scrollgrid-section-body",
    dayRowClass: "fc-daygrid-row",
};

function composeClassGenerators(compat, custom) {
    if (!custom) {
        return compat;
    }
    return (info) =>
        joinClasses(
            typeof compat === "function" ? compat(info) : compat,
            typeof custom === "function" ? custom(info) : custom
        );
}

/**
 * Luxon format strings (e.g. `dayHeaderFormat: "EEE d"`) were handled by the luxon3 plugin,
 * removed in v7.
 */
const luxonFormatPlugin = {
    name: "odoo-luxon-format",
    cmdFormatter: (format, { date, timeZone, localeCodes }) => {
        const [year, month, day, hour, minute, second, millisecond] = date.array;
        return luxon.DateTime.fromObject(
            { year, month: month + 1, day, hour, minute, second, millisecond },
            { zone: timeZone, locale: localeCodes[0] }
        ).toFormat(format);
    },
};

/**
 * Time zones are resolved by Temporal, which only accepts IANA names and offsets, whereas the
 * luxon3 plugin also accepted luxon fixed-offset zone names (e.g. "UTC+1").
 */
function toTemporalTimeZone(name) {
    const zone = luxon.Info.normalizeZone(name);
    return zone.isUniversal ? zone.formatOffset(0, "short") : zone.name;
}

/**
 * @param {Object} options FullCalendar options
 * @returns {Object} options completed with what Odoo relies on from FullCalendar v6
 */
export function withCompatOptions(options) {
    const result = {
        ...options,
        plugins: [luxonFormatPlugin, ...(options.plugins || [])],
        timeZone: toTemporalTimeZone(options.timeZone),
    };
    for (const [name, compat] of Object.entries(COMPAT_CLASSES)) {
        const generator = composeClassGenerators(compat, options[name]);
        result[name] =
            typeof generator === "function"
                ? (info) => joinClasses(generator(info))
                : joinClasses(generator);
    }
    return result;
}
