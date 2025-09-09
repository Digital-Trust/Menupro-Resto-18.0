import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { patch } from "@web/core/utils/patch";

patch(Orderline.prototype, {
    selectLine(ev) {
        const pos = this.env.services.pos;
        const currentOrder = pos.get_order();
        if (currentOrder && currentOrder.takeaway === true) {
            console.log("Orderline click disabled: order is takeaway");
            ev.preventDefault();
            ev.stopPropagation();
            return false;
        }
        return super.selectLine(...arguments);
    }
});