/* @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ActionpadWidget } from "@point_of_sale/app/screens/product_screen/action_pad/action_pad";

const disableInteractionOnOldOrders = (orderLines, isAdmin) => {
  console.log("disableInteractionOnOldOrders");
  orderLines.forEach((line) => {
    // Only disable interaction for orders that have been sent to kitchen (don't have has-change class)
    if (
      !isAdmin &&
      line.classList.contains("orderline") &&
      !line.classList.contains("text-success") &&
      !line.classList.contains("has-change")
    ) {
      line.classList.remove("cursor-pointer");
      line.style.pointerEvents = "none";
      line.style.userSelect = "none";
      line.style.cursor = "not-allowed";
    }
    // Re-enable interaction for orders that haven't been sent to kitchen (have has-change class)
    else if (
      line.classList.contains("orderline") &&
      line.classList.contains("has-change")
    ) {
      line.style.pointerEvents = "";
      line.style.userSelect = "";
      line.style.cursor = "";
      if (!line.classList.contains("cursor-pointer")) {
        line.classList.add("cursor-pointer");
      }
    }
  });
};

const removeSelectedClass = () => {
  console.log("removeSelectedClass");
  const selectedOrderLines = document.querySelectorAll(".orderline.selected");
  selectedOrderLines.forEach((el) => {
    el.classList.remove("selected");
  });
};

function checkForChanges() {
  let hasOtherChanges = false;
  const orderLines = document.querySelectorAll(".order-container .orderline");
  for (const line of orderLines) {
    if (line.classList.contains("has-change")) {
      hasOtherChanges = true;
      break;
    }
  }
  return hasOtherChanges;
}

patch(ActionpadWidget.prototype, {
  setup() {
    super.setup(...arguments);
    try {
      const pos = this.pos;
      const currentUser = pos.cashier;
      const isAdmin =
        currentUser._role === "admin" || currentUser._role === "manager";

      // Vérifier si la commande est en mode takeaway
      const isTakeawayOrder = () => {
        const currentOrder = pos.get_order();
        return currentOrder && currentOrder.takeaway === true;
      };

      setTimeout(() => {
        // Désactiver le bouton Actions et tous les boutons du numpad pour les commandes takeaway
        if (isTakeawayOrder()) {
          const actionsButton = document.querySelector(".more-btn");
          if (actionsButton) {
            actionsButton.disabled = true;
            actionsButton.style.pointerEvents = "none";
            actionsButton.style.opacity = "0.5";
            console.log("Actions button disabled: order is takeaway");
          }

          // Désactiver tous les boutons du numpad pour les commandes takeaway
          const numpadButtons = document.querySelectorAll(".numpad button");
          numpadButtons.forEach((button) => {
            button.disabled = true;
            button.style.pointerEvents = "none";
            button.style.opacity = "0.5";
          });
          console.log("All numpad buttons disabled: order is takeaway");
        }

        if (!isAdmin) {
          if (!checkForChanges()) {
            const numpadButtons = document.querySelectorAll(".numpad button");
            numpadButtons.forEach((button) => {
              button.disabled = true;
              button.style.pointerEvents = "none";
              console.log(" after ActionpadWidget call");
            });
          }

          const allOrderLines = document.querySelectorAll(".orderline");
          console.log("allOrderLines", allOrderLines);
          disableInteractionOnOldOrders(allOrderLines, isAdmin);

          const sentOrderLines = document.querySelectorAll(
            ".orderline:not(.has-change).selected"
          );
          sentOrderLines.forEach((el) => {
            el.classList.remove("selected");
          });
        }
      }, 100);

      // Observer to monitor UI changes
      const orderContainer = document.querySelector(".order-container");
      if (orderContainer) {
        const observer = new MutationObserver(() => {
          // Désactiver le bouton Actions et tous les boutons du numpad pour les commandes takeaway
          if (isTakeawayOrder()) {
            const actionsButton = document.querySelector(".more-btn");
            if (actionsButton) {
              actionsButton.disabled = true;
              actionsButton.style.pointerEvents = "none";
              actionsButton.style.opacity = "0.5";
            }

            // Désactiver tous les boutons du numpad pour les commandes takeaway
            const numpadButtons = document.querySelectorAll(".numpad button");
            numpadButtons.forEach((button) => {
              button.disabled = true;
              button.style.pointerEvents = "none";
              button.style.opacity = "0.5";
            });
          }

          if (!isAdmin) {
            const allOrderLines = document.querySelectorAll(".orderline");
            disableInteractionOnOldOrders(allOrderLines, isAdmin);

            if (!checkForChanges()) {
              const numpadButtons = document.querySelectorAll(".numpad button");
              numpadButtons.forEach((button) => {
                button.style.pointerEvents = "none";
                button.disabled = true;
              });
            } else {
              // Re-enable numpad if there are changes
              const numpadButtons = document.querySelectorAll(".numpad button");
              numpadButtons.forEach((button) => {
                button.style.pointerEvents = "";
                button.disabled = false;
              });
            }

            console.log("allOrderLines", allOrderLines);

            const sentOrderLines = document.querySelectorAll(
              ".orderline:not(.has-change).selected"
            );
            sentOrderLines.forEach((el) => {
              el.classList.remove("selected");
            });
          }
        });
        observer.observe(orderContainer, { subtree: true, childList: true });
      }
    } catch (error) {
      console.error(
        "Une erreur s'est produite dans le patch de ProductScreen :",
        error
      );
    }
  },

  async submitOrder() {
    const res = await super.submitOrder();
    this.pos.showScreen("FloorScreen");
    return res;
  },
});
