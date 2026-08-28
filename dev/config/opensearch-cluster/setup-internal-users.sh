#!/usr/bin/env bash

# Les comptes du cluster sont rendus hors conteneur puis charges une seule fois
# par initialize-security.sh. L'initialisation mono-noeud de l'image est donc
# volontairement neutralisee.
exit 0
