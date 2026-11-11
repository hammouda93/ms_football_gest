"""Runtime, policy-filtered Django metadata: never evaluates model properties."""
import hashlib
import json
from pathlib import Path
from django.apps import apps

POLICY = json.loads((Path(__file__).parent / 'policy.json').read_text(encoding='utf-8'))['models']


def catalog():
    models = {}
    for entity, allowed in POLICY.items():
        model = apps.get_model(entity)
        fields, reverse = {}, {}
        for field in model._meta.get_fields():
            if field.concrete and not field.many_to_many and field.name in allowed:
                fields[field.name] = {'name': field.name, 'type': field.get_internal_type(),
                    'nullable': field.null, 'primaryKey': field.primary_key,
                    'choices': list(field.flatchoices) if field.choices else []}
                if field.is_relation:
                    fields[field.name].update(target=field.related_model._meta.label_lower, cardinality='one')
            elif field.auto_created and not field.concrete and field.related_model._meta.label_lower in POLICY:
                child = field.related_model._meta.label_lower
                if field.field.name in POLICY[child]:
                    reverse[field.name] = {'target': child, 'field': field.field.name,
                                           'cardinality': 'many' if field.one_to_many or field.many_to_many else 'one'}
        models[entity] = {'entity': entity, 'label': str(model._meta.verbose_name_plural),
                         'fields': fields, 'reverseRelations': reverse}
    content = json.dumps(models, sort_keys=True, ensure_ascii=False, default=str)
    return {'catalogVersion': 1, 'models': models,
            'schemaFingerprint': hashlib.sha256(content.encode()).hexdigest(),
            'businessRules': [
                {'id': 'problematic', 'rule': 'problematic = projet mis de côté, exclu de la production active et des urgences.', 'provenance': 'user-confirmed'},
                {'id': 'grain', 'rule': 'Ne pas confondre joueur, commande, paiement, abonnement et joueur-match. Agréger les branches multiples séparément.', 'provenance': 'models-and-user-rules'},
                {'id': 'money', 'rule': 'Séparer devises et services. Paiement enregistré ne prouve pas un virement bancaire.', 'provenance': 'user-confirmed'},
                {'id': 'history', 'rule': 'Les statistiques synchronisées peuvent remplacer des valeurs. Ne pas inventer un historique non enregistré.', 'provenance': 'source-inspected'}
            ]}
