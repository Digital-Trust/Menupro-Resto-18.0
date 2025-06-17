/** @odoo-module **/

import { registry } from "@web/core/registry";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError } from "@web/core/network/rpc";

registry.category("error_handlers").remove("offlineErrorHandler");

function customOfflineErrorHandler(env, error, originalError) {
    if (originalError instanceof ConnectionLostError) {
        if (!env.services.pos.data.network.warningTriggered) {
            env.services.dialog.add(AlertDialog, {
                title: _t("Connexion perdue"),
                body: _t("La caisse continue en mode hors-ligne. Certaines fonctionnalités peuvent être limitées jusqu’au rétablissement de la connexion."),
                confirmLabel: _t("Continuer"),
            });
            env.services.pos.data.network.warningTriggered = true;
        }
        return true;
    }
}

registry.category("error_handlers").add("offlineErrorHandler", customOfflineErrorHandler);
