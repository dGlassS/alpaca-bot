# Bot de trading Alpaca (Paper Trading uniquement)

Bot automatique de day trading sur actions américaines, **en argent fictif**.
Le mode Paper est écrit en dur dans le code (`paper=True`) : il ne peut pas toucher un compte réel.

## La stratégie : cassure du range d'ouverture (ORB 15 min)

1. De 9h30 à 9h45 (New York), le bot note le plus haut et le plus bas de chaque action.
2. Après 9h45, si une bougie d'1 minute **clôture au-dessus du plus haut**, il achète.
3. **Stop** au milieu du range, **objectif** à 2 fois le risque (ordre « bracket » chez Alpaca).
4. Il n'achète pas si le prix est déjà parti trop loin, ni si le range est trop petit ou trop grand.
5. À 15h55, il ferme tout. Jamais de position la nuit.

Actions surveillées : SPY, QQQ, AAPL, MSFT, NVDA, AMD, TSLA, META, AMZN, GOOGL.

## Les limites (identiques au skill trader-risk)

| Limite | Valeur |
|---|---|
| Perte max par trade | 50 $ |
| Perte max par jour | 150 $ |
| Trades max par jour | 2 |
| Reward:risk minimum | 1,5 |
| Taille d'un ordre | 100 $ à 10 000 $, et 10 % du compte max |
| Fenêtre d'entrée | 9h45 à 15h30, heure de New York |
| Interdit | marge, vente à découvert, options, crypto |

Tout est dans `bot/config.py`.

## Arrêt d'urgence

- **Depuis le téléphone** : sur le site Alpaca, crée une **watchlist nommée `STOP`**.
  Le bot ferme tout et n'achète plus rien. Supprime la watchlist pour le relancer.
- **Depuis le serveur** : `sudo touch /opt/alpaca-bot/STOP` (et `sudo rm /opt/alpaca-bot/STOP` pour relancer),
  ou `sudo systemctl stop alpaca-bot`.

## Installation sur le serveur (Ubuntu 24.04)

```bash
curl -fsSL https://raw.githubusercontent.com/dGlassS/alpaca-bot/main/deploy/install.sh -o install.sh
sudo bash install.sh
```

Le script demande les clés Alpaca **Paper** et les range dans `/etc/alpaca-bot.env` (lisible par root seulement).
Relancer la même commande met le bot à jour.

## Commandes utiles

```bash
sudo journalctl -u alpaca-bot -f          # voir le bot en direct
sudo systemctl restart alpaca-bot         # redémarrer
cat /opt/alpaca-bot/logs/journal.jsonl    # historique des achats, blocages, fermetures
```

## Tests

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

Outil d'apprentissage, pas un conseil financier. La plupart des stratégies de day trading perdent de l'argent.
