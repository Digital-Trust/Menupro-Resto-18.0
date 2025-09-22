import { OrderTabs } from "@point_of_sale/app/components/order_tabs/order_tabs";
import { patch } from "@web/core/utils/patch";

patch(OrderTabs.prototype, {
    newFloatingOrder() {
//        this.pos.selectedTable = null;
//        const order = this.pos.add_new_order();
//        this.pos.showScreen("ProductScreen");
//        this.dialog.closeAll();
//        return order;
    },


    selectFloatingOrder(order) {
        if (this.pos.cashier.can_manage_takeaway_orders === false) {
            return;
        }
        this.pos.set_order(order);
        this.pos.selectedTable = null;
        const previousOrderScreen = order.get_screen_data();

        const props = {};
        if (previousOrderScreen?.name === "PaymentScreen") {
            props.orderUuid = order.uuid;
        }

        this.pos.showScreen(previousOrderScreen?.name || "ProductScreen", props);
        this.dialog.closeAll();
    }
});
