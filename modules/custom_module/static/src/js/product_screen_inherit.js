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
    const currentOrder = this.pos.get_order();
  },

  get isTakeawayMode() {
    const currentOrder = this.pos.get_order();
    return (
      currentOrder &&
      currentOrder.takeaway === true &&
      currentOrder.table_id === false
    );
  },

  isManagerOrAdmin() {
    const cashier = this.pos.get_cashier();
    return (
      cashier && (cashier._role === "manager" || cashier._role === "admin")
    );
  },

  // Désactiver l'ajout de produits si takeaway === true
  async addProductToOrder(product) {
    if (this.isTakeawayMode) {
      console.log("Product addition disabled: order is takeaway");
      this.notification.add(_t("Cannot modify takeaway orders"), {
        type: "warning",
      });
      return;
    }
    return super.addProductToOrder(...arguments);
  },

  // Désactiver les inputs du numpad si takeaway === true
  onNumpadClick(buttonValue) {
    if (this.isTakeawayMode) {
      console.log("Numpad input disabled: order is takeaway");
      this.notification.add(_t("Cannot modify takeaway orders"), {
        type: "warning",
      });
      return;
    }

    if (buttonValue === "price" && !this.isManagerOrAdmin()) {
      console.log("Price button disabled: user is not manager or admin");
      this.notification.add(_t("Only managers can modify prices"), {
        type: "warning",
      });
      return;
    }

    return super.onNumpadClick(...arguments);
  },

  onProductCardClick(product) {
    if (this.isTakeawayMode) {
      console.log("Product click disabled: order is takeaway");
      this.notification.add(_t("Cannot modify takeaway orders"), {
        type: "warning",
      });
      return;
    }
    return this.addProductToOrder(product);
  },

  async submitOrder() {
    if (!this.uiState.clicked) {
      this.uiState.clicked = true;
      try {
        await this.pos.sendOrderInPreparationUpdateLastChange(
          this.currentOrder
        );
        this.pos.addPendingOrder([this.currentOrder.id]);
      } finally {
        this.uiState.clicked = false;
        this.pos.showScreen("FloorScreen");
      }
    }
  },

  getNumpadButtons() {
    const isTakeaway = this.isTakeawayMode;

    const colorClassMap = {
      [this.env.services.localization.decimalPoint]:
        "o_colorlist_item_color_transparent_6",
      Backspace: "o_colorlist_item_color_transparent_1",
      "-": "o_colorlist_item_color_transparent_3",
    };
    return getButtons(DEFAULT_LAST_ROW, [
      {
        value: "quantity",
        text: _t("Qty"),
        disabled: isTakeaway,
      },
      {
        value: "discount",
        text: _t("%"),
        disabled: !this.pos.config.manual_discount || isTakeaway,
      },
      {
        value: "price",
        text: _t("Price"),
        disabled:
          !this.pos.cashierHasPriceControlRights() ||
          isTakeaway ||
          !this.isManagerOrAdmin(),
      },
      {
        ...BACKSPACE,
        disabled: isTakeaway,
      },
    ]).map((button) => ({
      ...button,
      class: `
                ${colorClassMap[button.value] || ""}
                ${
                  this.pos.numpadMode === button.value && !button.disabled
                    ? "active"
                    : ""
                }
                ${
                  button.value === "quantity"
                    ? "numpad-qty rounded-0 rounded-top mb-0"
                    : ""
                }
                ${
                  button.value === "price"
                    ? "numpad-price rounded-0 rounded-bottom mt-0"
                    : ""
                }
                ${
                  button.value === "discount"
                    ? "numpad-discount my-0 rounded-0 border-top border-bottom"
                    : ""
                }
                ${button.disabled ? "disabled opacity-50" : ""}
            `,
    }));
  },
});
