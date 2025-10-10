/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";


function sanitizeLine(line) {
    return {
        line_id: line.id,
        full_product_name: line.full_product_name,
        saved_quantity: line.saved_quantity,
        discount: line.discount,
        note: line.note || line.customer_note || "",
        price_unit: line.price_unit,
        price_subtotal: line.price_subtotal,
        price_subtotal_incl: line.price_subtotal_incl,
        line_status: line.line_status,
        menupro_id: line.menupro_id || null,
        product: {
            id: line.product_id?.id,
            default_code: line.product_id?.default_code || null,
            lst_price: line.product_id?.lst_price,
        },
        order_id: line.order_id?.id,
    };
}
async function getRestaurantId() {
    try {
        const result = await rpc("/web/dataset/call_kw/ir.config_parameter/get_param", {
            model: "ir.config_parameter",
            method: "get_param",
            args: ["restaurant_id"],
            kwargs: {},
        });
        return result || null;
    } catch (error) {
        console.error("Erreur récupération restaurant_id:", error);
        try {
            const result = await rpc({
                route: "/web/dataset/call_kw",
                params: {
                    model: "ir.config_parameter",
                    method: "get_param",
                    args: ["restaurant_id"],
                    kwargs: {},
                }
            });
            return result || null;
        } catch (altError) {
            console.error("Alternative method also failed:", altError);
            return null;
        }
    }
}


function generateLocalTicketNumber() {
    const today = new Date();
    const todayString = today.toDateString();
    const lastResetDate = localStorage.getItem("pos.last_reset_date");
    let currentCounter = parseInt(localStorage.getItem("pos.ticket_number")) || 0;

    let newTicketNumber;
    if (lastResetDate !== todayString) {
        newTicketNumber = 0;
        localStorage.setItem("pos.last_reset_date", todayString);
    } else {
        newTicketNumber = currentCounter + 1;
    }

    localStorage.setItem("pos.ticket_number", newTicketNumber.toString());
    return newTicketNumber;
}

async function getTicketNumber(orderId) {
    try {
        const response = await fetch('/custom_module/ticketNumber', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_id: orderId }),
        });
        if (response.ok) {
            const data = await response.json();
            return data.result.ticket_number;
        }
    } catch (error) {
        console.warn("Offline mode or server error", error);
    }
    return 0;
}
patch(PosOrder.prototype, {

    async setup(vals) {
        await super.setup(vals);

        try {
            const result = await getTicketNumber(parseInt(vals.id));

            if (typeof result === "number" && result !== undefined && result !== null) {
                this.ticket_number = result;
                vals.ticket_number = result;
                localStorage.setItem("pos.ticket_number", result.toString());
            } else {
                const localTicketNumber = generateLocalTicketNumber();
                this.ticket_number = localTicketNumber;
                vals.ticket_number = localTicketNumber;
                console.warn("getTicketNumber returned undefined or invalid, using fallback");
            }
        } catch (error) {
            const fallbackNumber = generateLocalTicketNumber();
            this.ticket_number = fallbackNumber;
            vals.ticket_number = fallbackNumber;
            console.error("Error in setup ticket number, fallback to offline", error);
        }
    },

     /**
     * A wrapper around line.delete() that may potentially remove multiple orderlines.
     * In core pos, it removes the linked combo lines. In other modules, it may remove
     * other related lines, e.g. multiple reward lines in pos_loyalty module.
     * @param {Orderline} line
     * @returns {boolean} true if the line was removed, false otherwise
     */
    async removeOrderline(line) {
        const linesToRemove = line.getAllLinesInCombo();

        const cashier_id = Number(sessionStorage.getItem(`connected_cashier_${this.config.id}`));
        const currentCashier = this.models["hr.employee"].get(cashier_id);

        let restaurantId;
        try {
            restaurantId = await getRestaurantId();
            this.restaurant_id = restaurantId;
        } catch (error) {
            console.error("Erreur récupération restaurant_id:", error);
            restaurantId = null;
        }

        for (const lineToRemove of linesToRemove) {
            if (lineToRemove.refunded_orderline_id?.uuid in this.uiState.lineToRefund) {
                delete this.uiState.lineToRefund[lineToRemove.refunded_orderline_id.uuid];
            }

            if (this.assert_editable()) {
                if (this.cashier) {
                    try {
                        const cashierResult = await rpc("/pos/update_cashier", {
                            order_id: this.id,
                            cashier_id: currentCashier.id
                        });

                        if (!cashierResult.success) {
                            console.error("Erreur mise à jour cashier:", cashierResult.error);
                        }
                    } catch (error) {
                        console.error("Erreur lors de la mise à jour du cashier:", error);
                    }
                }

                if (this.mobile_user_id != false && typeof lineToRemove.id === 'number') {
                    try {
                        const notificationResult = await rpc("/pos/send_removed_dish_notification", {
                            line_data: sanitizeLine(lineToRemove),
                            cashier_name: currentCashier.name,
                            order_id: this.id,
                            mobile_user_id: this.mobile_user_id,
                            subscription_id: this.subscription_id,
                            order_menupro_id: this.menupro_id,
                            restaurant_id: restaurantId,
                        });

                        if (notificationResult.success) {
                            console.log("Notification envoyée:", notificationResult.data);
                        } else {
                            console.error("Erreur notification:", notificationResult.error);
                        }
                    } catch (error) {
                        console.error("Erreur lors de l'envoi de notification:", error);
                    }
                }

                lineToRemove.delete();

                try {
                   if (typeof this.id === 'number') {
                        await rpc("/web/dataset/call_kw/pos.order/write", {
                            model: "pos.order",
                            method: "write",
                            args: [[this.id], {
                                cashier: currentCashier.name,
                                employee_id: currentCashier.id,
                            }],
                            kwargs: {},
                        });
                   } else {
                        console.log("Order not yet saved to database, skipping cashier update");
                   }
                } catch (error) {
                    console.error("Erreur lors de la mise à jour du cashier:", error);
                }
            }
        }
        if (!this.lines.length) {
            this.general_note = "";
        }
        return true;
    }
});