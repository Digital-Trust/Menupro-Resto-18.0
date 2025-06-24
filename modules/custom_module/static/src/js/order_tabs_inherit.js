import { OrderTabs } from "@point_of_sale/app/components/order_tabs/order_tabs";
import { patch } from "@web/core/utils/patch";

patch(OrderTabs.prototype, {
    newFloatingOrder() {
//        this.pos.selectedTable = null;
//        const order = this.pos.add_new_order();
//        this.pos.showScreen("ProductScreen");
//        this.dialog.closeAll();
//        return order;
    }
});
