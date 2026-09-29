import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as ReceiptScreen from "@point_of_sale/../tests/pos/tours/utils/receipt_screen_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";

import { registry } from "@web/core/registry";

/**
 * HELPERS
 */

function isQRDisplayedinDialog() {
    return [
        Dialog.is({ title: "QR Code" }),
        {
            content: "Verify QR image is displayed",
            trigger: ".modal-content img[src^='data:image/png;base64,']",
            run: "click",
        },
    ].flat();
}

function addProductandPay(isPartialPay = false) {
    return [
        ProductScreen.addOrderline("Hand Bag", "10"),
        ProductScreen.selectedOrderlineHas("Hand Bag", "10"),
        ProductScreen.clickPayButton(),

        PaymentScreen.totalIs("48"),
        ...(isPartialPay
            ? [
                  PaymentScreen.clickPaymentMethod("QR Code"),
                  PaymentScreen.clickNumpad("⌫"),
                  PaymentScreen.clickNumpad("+10"),
              ]
            : [PaymentScreen.clickPaymentMethod("QR Code", true, { amount: "48" })]),
        {
            content: "Display QR Code Payment dialog",
            trigger: ".button.send_payment_request.highlight",
            run: "click",
        },
    ].flat();
}

/**
 * TOURS
 */

registry.category("web_tour.tours").add("PaymentScreenWithQRPaymentFailure", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            addProductandPay(),
            Dialog.is({ title: "Failure to generate Payment QR Code" }),
            Dialog.confirm(),
        ].flat(),
});

registry.category("web_tour.tours").add("PaymentScreenWithQRPayment", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),

            // --- FULL PAYMENT ---
            addProductandPay(),
            isQRDisplayedinDialog(),
            Dialog.cancel(),
            PaymentScreen.validateButtonIsHighlighted(false),
            {
                content: "Retry to display QR Code Payment dialog",
                trigger: ".button.send_payment_request.highlight",
                run: "click",
            },
            isQRDisplayedinDialog(),
            Dialog.confirm(),
            {
                content: "Immediately at the receipt screen.",
                trigger: '.receipt-screen .button.next.highlight:contains("New Order")',
                run: "click",
            },

            // --- PARTIAL PAYMENT ---
            addProductandPay(true),
            isQRDisplayedinDialog(),
            Dialog.confirm(),
            {
                trigger: ".electronic_status:contains('Successful')",
            },
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
        ].flat(),
});

registry.category("web_tour.tours").add("test_fast_payment_with_qr_method", {
    steps: () =>
        [
            Chrome.startPoS(),

            ProductScreen.addOrderline("Hand Bag", "10"),
            ProductScreen.selectedOrderlineHas("Hand Bag", "10"),

            // Trigger the quick payment flow with the QR Code method.
            ProductScreen.clickFastPaymentButton("QR Code"),
            isQRDisplayedinDialog(),

            // Cancel the QR dialog and ensure the POS screen is still active.
            Dialog.cancel(),
            ProductScreen.isShown(),

            // Retry the quick payment and confirm the QR dialog before finishing.
            ProductScreen.clickFastPaymentButton("QR Code"),
            isQRDisplayedinDialog(),
            Dialog.confirm(),
            ReceiptScreen.isShown(),
        ].flat(),
});

registry.category("web_tour.tours").add("PaymentScreenWithQRPaymentSwiss", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.addOrderline("Hand Bag", "10"),
            ProductScreen.selectedOrderlineHas("Hand Bag", "10"),
            ProductScreen.clickPartnerButton(),
            ProductScreen.clickCustomer("AAA Partner Swiss"),
            ProductScreen.clickPayButton(),
            PaymentScreen.totalIs("48"),
            PaymentScreen.clickPaymentMethod("QR Code", true, { amount: "48" }),
            {
                content: "Display QR Code Payment dialog",
                trigger: ".button.send_payment_request.highlight",
                run: "click",
            },
            PaymentScreen.validateButtonIsHighlighted(false),
            isQRDisplayedinDialog(),
            Dialog.confirm(),
            {
                content: "Immediately at the receipt screen.",
                trigger: '.receipt-screen .button.next.highlight:contains("New Order")',
                run: "click",
            },
        ].flat(),
});
