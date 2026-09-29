import { expect, test } from "@odoo/hoot";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";
import { getSelectedCustomPtav } from "@sale/js/sale_utils";

/**
 * Confirming while an attribute change's `_updateCombination` is still pending used to save
 * `getSelectedCustomPtav`'s match against stale `attribute_values` instead of the RPC's answer.
 * `isPossibleConfiguration` now also checks each line's `isLoading` to block Confirm meanwhile.
 */
function makeDialog(product, { resolveCombination } = {}) {
    return Object.assign(Object.create(ProductConfiguratorDialog.prototype), {
        state: { products: [product] },
        _findProduct: () => product,
        _getCombination: () => [],
        _getParentsCombination: () => false,
        _getChildProducts: () => [],
        _updateCombination: () =>
            new Promise((resolve) => {
                if (resolveCombination) {
                    resolveCombination.resolve = resolve;
                }
            }),
    });
}

// OLD_PTAV: "-", not custom. NEW_CUSTOM_PTAV: "Custom", is_custom.
const OLD_PTAV = 1;
const NEW_CUSTOM_PTAV = 2;
const PTAL_ID = 100;

function makeProduct() {
    return {
        id: 55,
        product_tmpl_id: 10,
        quantity: 1,
        exclusions: false,
        parent_exclusions: false,
        archived_combinations: false,
        attribute_lines: [
            {
                id: PTAL_ID,
                selected_attribute_value_ids: [OLD_PTAV],
                // Pre-switch state, not yet refreshed with the RPC's answer.
                attribute_values: [
                    { id: OLD_PTAV, is_custom: false, excluded: false },
                    { id: NEW_CUSTOM_PTAV, is_custom: true, excluded: false },
                ],
                customValue: undefined,
            },
        ],
    };
}

test("selecting a value updates selected_attribute_value_ids before the combination RPC resolves", async () => {
    const product = makeProduct();
    const gate = {};
    const dialog = makeDialog(product, { resolveCombination: gate });

    const pending = dialog._updateProductTemplateSelectedPTAV(10, PTAL_ID, NEW_CUSTOM_PTAV, false);

    // Mid-flight: attribute_lines/attribute_values are still untouched.
    const ptal = product.attribute_lines[0];
    expect(ptal.selected_attribute_value_ids).toEqual([NEW_CUSTOM_PTAV]);
    expect(ptal.attribute_values.map((v) => v.id)).toEqual([OLD_PTAV, NEW_CUSTOM_PTAV]);

    gate.resolve({ attribute_lines: [] });
    await pending;
});

test("isPossibleConfiguration is false while an attribute update is in flight", async () => {
    const product = makeProduct();
    const gate = {};
    const dialog = makeDialog(product, { resolveCombination: gate });

    const pending = dialog._updateProductTemplateSelectedPTAV(10, PTAL_ID, NEW_CUSTOM_PTAV, false);

    // Still pending: Confirm must stay blocked.
    expect(product.attribute_lines[0].isLoading).toBe(true);
    expect(dialog.isPossibleConfiguration()).toBe(false);

    gate.resolve({ attribute_lines: [] });
    await pending;

    expect(dialog.isPossibleConfiguration()).toBe(true);
});

test("mid-update, getSelectedCustomPtav would match the new selection against stale attribute_values", async () => {
    const product = makeProduct();
    const gate = {};
    const dialog = makeDialog(product, { resolveCombination: gate });

    const pending = dialog._updateProductTemplateSelectedPTAV(10, PTAL_ID, NEW_CUSTOM_PTAV, false);

    // What applyProduct() reads to build the saved custom-value records.
    const ptal = product.attribute_lines[0];
    const selectedCustomPtav = getSelectedCustomPtav(ptal);

    // Found in the stale attribute_values, with no text typed for it yet.
    expect(selectedCustomPtav).not.toBe(undefined);
    expect(selectedCustomPtav.id).toBe(NEW_CUSTOM_PTAV);
    expect(ptal.customValue).toBe(undefined);

    gate.resolve({ attribute_lines: [] });
    await pending;
});

test("once attribute_lines is refreshed post-RPC, a dropped custom option is no longer found", () => {
    const ptal = {
        id: PTAL_ID,
        selected_attribute_value_ids: [NEW_CUSTOM_PTAV],
        attribute_values: [{ id: OLD_PTAV, is_custom: false, excluded: false }],
    };
    expect(getSelectedCustomPtav(ptal)).toBe(undefined);
});
