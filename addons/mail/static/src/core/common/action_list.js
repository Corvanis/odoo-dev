import { attClassObjectToString } from "@mail/utils/common/format";
import { propSignal } from "@mail/utils/common/hooks";
import { Component, computed, onWillUnmount, shallowEqual, t, useProps } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { Action as ActionModel, ACTION_TAGS } from "@mail/core/common/action";
import { useService } from "@web/core/utils/hooks";

const actionListProps = [
    "inline?",
    "dropdown?",
    "fw?",
    "hasBtnBg?",
    "odooControlPanelSwitchStyle?",
];

const actionListPropsSchema = {
    dropdown: t.boolean().optional(),
    fw: t.boolean().optional(true),
    hasBtnBg: t.boolean().optional(),
    inline: t.boolean().optional(),
    odooControlPanelSwitchStyle: t.boolean().optional(),
};

/**
 * Base of the components that render an action in an ActionList: @see InlineAction and
 * @see DropdownAction, which are used by all actions by default. An action that needs UI tweaks
 * gives an extension of them in its definition (`inlineActionComponent`, `dropdownActionComponent`).
 * The classes of the button are split by concern, so that an extension overrides just the concern it
 * tweaks, e.g. `get paddingClass() { return { ...super.paddingClass, "px-3": true }; }`.
 */
export class BaseAction extends Component {
    static template = "";

    get ActionList() {
        return ActionList;
    }

    get Dropdown() {
        return Dropdown;
    }

    setup() {
        super.setup();
        this.props = useProps({
            action: t.instanceOf(ActionModel),
            isFirstInGroup: t.boolean().optional(),
            isLastInGroup: t.boolean().optional(),
            style: t.string().optional(),
            ...actionListPropsSchema,
        });
        this.store = useService("mail.store");
        this.ui = useService("ui");
        if (this.props.action.definition?.isMoreAction) {
            onWillUnmount(() => {
                this.props.action.dropdownState.close();
            });
        }
    }

    get action() {
        return this.props.action;
    }

    get attrs() {
        return {
            "aria-label": this.action.name,
            disabled: this.action.disabledCondition,
            name: this.action.id,
            "data-sequence": this.action.sequence,
            "data-sequence-group": this.action.sequenceGroup,
            "data-sequence-quick": this.action.sequenceQuick,
            ...this.action.btnAttrs,
        };
    }

    get btnClass() {
        return [
            this.coreClass,
            this.alignmentClass,
            this.borderClass,
            this.roundnessClass,
            this.marginClass,
            this.paddingClass,
            this.themeClass,
            this.dynamicClass,
        ]
            .map(attClassObjectToString)
            .filter(Boolean)
            .join(" ");
    }

    get coreClass() {
        const tags = this.action.tags;
        return {
            "o-mail-ActionList-button btn position-relative": true,
            "o-first": this.props.isFirstInGroup,
            "o-last": this.props.isLastInGroup,
            active: this.action.isActive,
            "o-odooControlPanelSwitchStyle": this.props.odooControlPanelSwitchStyle,
            "o-hasBtnBg": this.hasBtnBg,
            "btn-secondary":
                !tags.includes(ACTION_TAGS.PRIMARY) &&
                !tags.includes(ACTION_TAGS.DANGER) &&
                !tags.includes(ACTION_TAGS.SUCCESS),
            "btn-primary": tags.includes(ACTION_TAGS.PRIMARY),
            "btn-danger": tags.includes(ACTION_TAGS.DANGER),
            "btn-success": tags.includes(ACTION_TAGS.SUCCESS),
        };
    }

    get alignmentClass() {
        return {};
    }

    get borderClass() {
        return {};
    }

    get roundnessClass() {
        return {};
    }

    get marginClass() {
        return {};
    }

    get paddingClass() {
        return {};
    }

    get themeClass() {
        const simulateDarkTheme = this.store.shouldSimulateDarkTheme(this);
        return {
            "o-text-white o-simulateDarkTheme": simulateDarkTheme,
            "bg-transparent": simulateDarkTheme && !this.hasBtnBg,
            "o-inDiscussCall":
                this.env.inDiscussCallView ||
                this.env.inCallInvitation ||
                this.env.isDiscussPipBanner ||
                this.env.inWelcomePage,
        };
    }

    get dynamicClass() {
        return {
            [this.action.btnClass ?? ""]: true,
            [this.action.tagClassNames]: true,
        };
    }

    get hasBtnBg() {
        return (
            this.props.odooControlPanelSwitchStyle ||
            this.props.hasBtnBg ||
            this.props.action.hasBtnBg
        );
    }

    /** Whether the component of the action definition replaces the button of the action. */
    get hasDefinitionComponent() {
        return Boolean(this.action.component && this.action.componentCondition);
    }

    /**
     * The list then adds no rounding of its own: its segmented-control shape only rounds the outer
     * corners, which would leave the rest lopsided.
     */
    get hasOwnRounding() {
        return /(^|\s)rounded(-|\s|$)/.test(this.action.btnClass ?? "");
    }

    get iconClass() {
        return { "oi-fw": this.props.fw };
    }

    get label() {
        return this.action.name;
    }

    get labelClass() {
        return {};
    }

    get showLabel() {
        return Boolean(this.action.name);
    }

    onSelected(action, ev) {
        action.onSelected?.(ev);
    }
}

/** Default component of an action in an inline ActionList, i.e. a button. */
export class InlineAction extends BaseAction {
    static template = "mail.InlineAction";

    get inMeetingViewCallButtonsFullscreen() {
        return Boolean(
            this.props.inline &&
                this.env.inMeetingView &&
                !this.env.inComposer &&
                !this.env.inDiscussActionPanel &&
                this.store.rtc.isFullscreen
        );
    }

    get isCircleButton() {
        return Boolean(
            this.props.inline && this.action.icon && (this.env.inComposer || this.env.inMessage)
        );
    }

    get coreClass() {
        return {
            ...super.coreClass,
            "btn-group-item": true,
            "o-inline": this.props.inline,
            o_btn_circle: this.isCircleButton,
        };
    }

    get alignmentClass() {
        return { "d-flex align-items-center": this.isCircleButton };
    }

    get borderClass() {
        const noBtnBg = this.props.inline && !this.hasBtnBg;
        return {
            "border-0": noBtnBg && this.action.icon,
            "border-2": noBtnBg && !this.action.icon,
        };
    }

    get roundnessClass() {
        const rounded = this.props.inline && !this.hasOwnRounding;
        return {
            "rounded-circle": rounded && this.isCircleButton,
            "rounded-start-3": rounded && !this.isCircleButton && this.props.isFirstInGroup,
            "rounded-end-3": rounded && !this.isCircleButton && this.props.isLastInGroup,
        };
    }

    get marginClass() {
        return { "o-mx-0_5": this.props.inline && !this.hasBtnBg && !this.action.icon };
    }

    get paddingClass() {
        return {
            "px-1 py-2": this.inMeetingViewCallButtonsFullscreen,
            "o-px-0_5":
                this.props.inline && !this.env.inMeetingView && !this.hasBtnBg && !this.action.icon,
        };
    }

    get attrs() {
        return { ...super.attrs, title: this.action.name };
    }

    get iconClass() {
        return {
            ...super.iconClass,
            "oi-lg": this.inMeetingViewCallButtonsFullscreen,
            "py-1": this.inMeetingViewCallButtonsFullscreen && !this.isCircleButton,
        };
    }

    get label() {
        return (this.props.inline && this.action.inlineName) || this.action.name;
    }

    get showLabel() {
        return Boolean(
            super.showLabel && this.props.inline && (!this.action.icon || this.action.inlineName)
        );
    }
}

/** Default component of an action in a dropdown ActionList, i.e. a dropdown item. */
export class DropdownAction extends BaseAction {
    static components = { DropdownItem };
    static template = "mail.DropdownAction";

    get alignmentClass() {
        return {
            "d-flex align-items-center dropdown-item_active_noarrow": true,
            "text-start": !this.ui.isSmall,
            "gap-2": this.ui.isSmall,
            "gap-1": !this.ui.isSmall,
        };
    }

    get paddingClass() {
        return {
            "px-3 py-2": this.ui.isSmall,
            "px-2 py-1": !this.ui.isSmall,
        };
    }

    get iconClass() {
        return { ...super.iconClass, "o-fs-small": true };
    }

    get labelClass() {
        return { ...super.labelClass, "mx-1": true };
    }
}

export class ActionList extends Component {
    static template = "mail.ActionList";

    /** @param {ActionModel} action */
    getActionComponent(action) {
        if (this.props.dropdown) {
            return action.dropdownActionComponent ?? DropdownAction;
        }
        return action.inlineActionComponent ?? InlineAction;
    }

    getActionProps(action, group, { index, isFirstInGroup, isLastInGroup } = {}) {
        return {
            action,
            group,
            isFirstInGroup,
            isLastInGroup,
            ...Object.fromEntries(
                actionListProps.map((propName) => {
                    const actualPropName = propName.endsWith("?")
                        ? propName.substring(0, propName.length - 1)
                        : propName;
                    return [actualPropName, this.props[actualPropName]];
                })
            ),
            style: `z-index: ${group.length - index + (action.hotkey ? 1 : 0)}`,
        };
    }

    setup() {
        super.setup();
        this.actions = propSignal(
            "actions",
            t.array(t.or([t.instanceOf(ActionModel), t.array(t.instanceOf(ActionModel))]))
        );
        this.props = useProps({
            groupClass: t.string().optional(),
            ...actionListPropsSchema,
        });
        this.store = useService("mail.store");
        this.ui = useService("ui");
        this.actionListProps = actionListProps;
    }

    groups = computed(
        () => {
            const actions = this.actions();
            let groups;
            if (actions.find((i) => Array.isArray(i))) {
                groups = actions;
            } else {
                groups = [actions];
            }
            return groups.filter((group) => group.length); // don't show empty groups
        },
        { equals: shallowEqual }
    );

    get hasBtnBg() {
        return this.props.odooControlPanelSwitchStyle || this.props.hasBtnBg;
    }
}
