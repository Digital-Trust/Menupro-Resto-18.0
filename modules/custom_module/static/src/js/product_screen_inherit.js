import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import {
    BACKSPACE,
    Numpad,
    getButtons,
    DEFAULT_LAST_ROW,
} from "@point_of_sale/app/generic_components/numpad/numpad";
import { _t } from "@web/core/l10n/translation";


patch(ProductScreen.prototype, {

    setup() {
        super.setup(...arguments);
        this.uiState = useState({
            clicked: false,
        });
    },

    async submitOrder() {
        if (!this.uiState.clicked) {
            this.uiState.clicked = true;
            try {
                await this.pos.sendOrderInPreparationUpdateLastChange(this.currentOrder);
                this.pos.addPendingOrder([this.currentOrder.id]);
            } finally {
                this.uiState.clicked = false;
                this.pos.showScreen("FloorScreen");

            }
        }
    },
    getNumpadButtons() {
        const colorClassMap = {
            [this.env.services.localization.decimalPoint]: "o_colorlist_item_color_transparent_6",
            Backspace: "o_colorlist_item_color_transparent_1",
            "-": "o_colorlist_item_color_transparent_3",
        };

        return getButtons(DEFAULT_LAST_ROW, [
            { value: "quantity", text: _t("Qty") },
            { value: "discount", text: _t("%"), disabled: !this.pos.config.manual_discount },
            {
                value: "price",
                text: _t("Price"),
                disabled: true,
            },
            BACKSPACE,
        ]).map((button) => ({
            ...button,
            class: `
                ${colorClassMap[button.value] || ""}
                ${this.pos.numpadMode === button.value ? "active" : ""}
                ${button.value === "quantity" ? "numpad-qty rounded-0 rounded-top mb-0" : ""}
                ${button.value === "price" ? "numpad-price rounded-0 rounded-bottom mt-0" : ""}
                ${
                    button.value === "discount"
                        ? "numpad-discount my-0 rounded-0 border-top border-bottom"
                        : ""
                }
            `,
        }));
    }

});
