# -*- coding: utf-8 -*-
"""
======================================================
Area-weighted Sum - Prorata surfacique (somme)
======================================================

Compute area-weighted sums of fields from an intersecting polygon layer.

Usage:
    - Load as a QGIS Processing script (toolbox)

──────────────────────────────────────────────────────
SPDX-License-Identifier: MIT
Copyright (c) 2025 Matthieu Lambert
Author: Matthieu Lambert
GitHub: https://github.com/Mothraa
Issues: https://github.com/Mothraa/gis-tools/issues
Date: 2025-08-31
Version: 0.1.0
QGIS-Compatibility: QGIS 3.36+ (tested on 3.40)
License: MIT (see LICENSE.md)
──────────────────────────────────────────────────────
"""

from qgis.PyQt.QtCore import QCoreApplication, QMetaType  # type: ignore
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingFeatureSource,
    QgsFeature,
    QgsField,
    QgsVectorLayer,
    QgsGeometry,
    QgsProcessingException,  # type: ignore
    QgsProcessingFeedback,
    QgsFeatureSink,
    QgsSpatialIndex,
    QgsProcessingContext,
    QgsFeatureRequest,
)


class ProrataSurfacique(QgsProcessingAlgorithm):

    INPUT = "INPUT"
    INTERSECT = "INTERSECT"
    FIELDS = "FIELDS"
    OUTPUT = "OUTPUT"

    def tr(self, string):
        return QCoreApplication.translate("ProrataSurfacique", string)

    def createInstance(self):
        return ProrataSurfacique()

    def name(self):
        return "prorata_surfacique"

    def displayName(self):
        return self.tr("Prorata surfacique (somme)")

    def group(self):
        return self.tr("Analyse spatiale")

    def groupId(self):
        return "analyse_spatiale"

    def shortHelpString(self):
        return self.tr(
            "Calcule un prorata surfacique (somme) "
            "d'une couche intersectante polygonale (ex : données statistiques au bâti, à l'IRIS,...) "
            "sur une couche principale polygonale (ex : zone de chalandise).\n"
            "Plusieurs champs peuvent être traités en même temps.\n"
            "Les champs doivent être dans un format numérique.\n"
            "Pour chaque entité de la couche principale :\n"
            "  • Le script cherche toutes les entités de la couche intersectante qui la "
            "chevauchent partiellement ou totalement.\n"
            "  • Il calcule la géométrie exacte de cette intersection.\n"
            "  • Les valeurs des champs choisis sont redistribuées proportionnellement "
            "à la surface intersectée (valeur * surface_intersection / surface_totale_intersectant).\n\n"
            "En sortie :\n"
            "  • une couche principale enrichie avec la somme des champs proratisés (suffix '_prorata'),"
        )

    def initAlgorithm(self, configuration=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT, self.tr("Couche principale"), [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INTERSECT, self.tr("Couche intersectante"), [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELDS,
                self.tr("Liste des champs à proratiser"),
                parentLayerParameterName=self.INTERSECT,
                type=QgsProcessingParameterField.Numeric,
                allowMultiple=True,
            )
        )
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr("Couche de sortie avec proratas")))

    def buildSpatialIndex(self, layer, feedback: QgsProcessingFeedback | None):
        """ build index spatial in memory (QGIS) """
        self._safe_push_info(feedback, "Création de l’index spatial en mémoire...")
        index = QgsSpatialIndex()
        for f in layer.getFeatures():
            index.addFeature(f)
        return index

    def prepareOutputFields(self, input_layer, fields_to_prorate):
        """ create proratized fields """
        output_fields = input_layer.fields()
        for f in fields_to_prorate:
            field_name = f"{f}_prorata"
            # verifie si le champ existe déjà
            if output_fields.indexFromName(field_name) == -1:
                # création du champ
                field = QgsField(field_name, QMetaType.Type.Double)
                field.setLength(10)
                field.setPrecision(5)
                output_fields.append(field)
        return output_fields

    def get_intersecting_features(
        self,
        layer: QgsVectorLayer,
        fids: list[int],
        geom: QgsGeometry
    ) -> list[QgsFeature]:
        """
        Retrieve features from a 'layer' that match feature IDs and intersect 'geom'.

        Args:
            layer: The vector layer from which to retrieve features.
            fids: List of feature IDs to filter in the layer. If empty, the function returns an empty list.
            geom: The geometry used for intersections.

        Returns:
            Features intersecting the provided geometry and matching the given IDs.
        """
        if not fids:
            return []

        request = QgsFeatureRequest().setFilterFids(fids)
        intersecting_feats = []

        for feat in layer.getFeatures(request):  # type: ignore
            geom_cand = feat.geometry()
            if geom_cand is None:
                continue
            if geom_cand.intersects(geom):
                # copie de la feature pour la conserver
                intersecting_feats.append(QgsFeature(feat))

        return intersecting_feats

    def _safe_push_info(self, feedback: QgsProcessingFeedback | None, message: str) -> None:
        """push an info message to feedback"""
        if feedback is None:
            return
        try:
            feedback.pushInfo(message)
        except RuntimeError:
            return
        except Exception:
            return

    def _safe_is_canceled(self, feedback: QgsProcessingFeedback | None) -> bool:
        """when user want to cancel script execution"""
        if feedback is None:
            return False
        try:
            return feedback.isCanceled()
        except RuntimeError:
            return False
        except Exception:
            return False

    # TODO : fonctions utilitaires a sortir de la class
    def _safe_float(self, value) -> float:
        """Convert any attribute value to float"""
        if value is None:
            return 0.0
        # cas int => float
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
        # cas QVariant
        try:
            return float(value.toDouble()[0])
        except (AttributeError, TypeError, ValueError):
            pass
        # cas string avec ','
        try:
            return float(str(value).replace(",", "."))
        except (ValueError, TypeError):
            return 0.0

    def computeProrata(
        self,
        feat: QgsFeature,
        inter_layer: QgsProcessingFeatureSource,
        spatial_index: QgsSpatialIndex,
        fields_to_prorate: list[str],
    ) -> dict[str, float] | None:
        """
        Compute proratized values for one feature

        This function calculates the proportion of each field to prorate
        prorated_value = field_value * (intersection_area / intersecting_feature_area)

        Args:
            feat (QgsFeature): The feature from the main layer to calculate prorata for.
            inter_layer (QgsProcessingFeatureSource): The intersecting layer containing features
                with fields to prorate.
            spatial_index (QgsSpatialIndex): Spatial index built on the intersecting layer
            fields_to_prorate (list[str]): List of field names to prorate

        Returns:
            dict: A dictionary with field names and prorated values
            Returns None if the geometry of the main feature is empty
        """
        # Récupere la geom de l'entité principale
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            return None

        # Intersection sur les bbox des entités pour optimisation des perfs
        inter_ids = spatial_index.intersects(geom.boundingBox())
        intersecting_feats = self.get_intersecting_features(inter_layer, inter_ids, geom)

        # Init à 0 des champs proratisés
        prorata_values = {f: 0.0 for f in fields_to_prorate}

        # Bouclage sur les entités intersectées
        for inter in intersecting_feats:
            inter_geom = inter.geometry().intersection(geom)

            # cas à ignorer (si intersect vide, cas spécifique, ne devrait pas se produire vu verif préalable)
            if not inter_geom or inter_geom.isEmpty():
                continue

            inter_area = inter.geometry().area()  # Surface totale de l'entité intersectante
            if inter_area <= 0:
                continue

            area = inter_geom.area()  # Surface de l'intersection

            # Calcul prorata pour chaque champ
            for field in fields_to_prorate:
                field_value = self._safe_float(inter.attribute(field))  # conversion en float
                prorata_values[field] += field_value * area / inter_area

        return prorata_values

    def createProrataFeature(self, feat, output_fields, prorata_values):
        """Generate the new feature with prorated values."""
        # On récup les attributs existante de l'entité d'origine
        attrs = feat.attributes()
        # on etend la liste d'attributs pour pouvoir mettre les nouveaux champs *_prorata (à None pour l'instant)
        attrs_extended = list(attrs) + [None] * (len(output_fields) - len(attrs))

        # creation de la nouvelle entité avec les champs ajoutés
        new_feat = QgsFeature(output_fields)
        # on récup la geom de l'entité source
        new_feat.setGeometry(feat.geometry())
        # init des attributs (nouveaux champs tjr à None)
        new_feat.setAttributes(attrs_extended)

        # On renseigne les valeurs dans les champs *_prorata
        for field, value in prorata_values.items():
            # Trouve l'index du champ de sortie correspondant (ex: "pop_prorata")
            idx = output_fields.indexOf(f"{field}_prorata")
            # Écriture de la valeur (avec un arrondi)
            # TODO : proposer un arrondi paramétrable
            new_feat.setAttribute(idx, round(value, 5))

        return new_feat

    def processAlgorithm(
        self, parameters,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback | None
    ):
        """ main processing """

        # Récupération des couches
        input_layer = self.parameterAsSource(parameters, self.INPUT, context)
        inter_layer = self.parameterAsSource(parameters, self.INTERSECT, context)

        if input_layer is None or inter_layer is None:
            raise QgsProcessingException("Impossible de charger la couche principale ou intersectante.")

        # on s'assure que getFeatures renvoie toujours un itérable
        input_features = list(input_layer.getFeatures())
        inter_features = list(inter_layer.getFeatures())

        if not input_features or not inter_features:
            raise QgsProcessingException("La couche principale ou intersectante ne contient aucune entité.")

        fields_to_prorate = self.parameterAsStrings(parameters, self.FIELDS, context)
        self._safe_push_info(feedback, f"Champs à proratiser : {fields_to_prorate}")

        spatial_index = self.buildSpatialIndex(inter_layer, feedback)
        output_fields = self.prepareOutputFields(input_layer, fields_to_prorate)

        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, output_fields, input_layer.wkbType(), input_layer.sourceCrs()
        )
        if sink is None:
            raise QgsProcessingException("Impossible de créer la couche de sortie.")

        nb_entites = 0
        total_features = input_layer.featureCount()
        # last_progress : pour éviter les répétitions dans le log, a améliorer a l'occasion mais fait le job...
        last_progress = -1

        for i, feat in enumerate(input_layer.getFeatures()):
            # Protéger isCanceled si feedback est None
            if self._safe_is_canceled(feedback):
                break

            prorata_values = self.computeProrata(feat, inter_layer, spatial_index, fields_to_prorate)
            if prorata_values is None:
                continue

            new_feat = self.createProrataFeature(feat, output_fields, prorata_values)
            # TODO : ajouter les entités par lot pour améliorer les perfs ?
            sink.addFeature(new_feat, QgsFeatureSink.FastInsert)

            nb_entites += 1

            # progression
            progress_percent = round((i + 1) / total_features * 100)
            # TODO : a mettre dans une fonction utilitaire
            if feedback is not None:
                feedback.setProgress(progress_percent)

            # push info uniquement aux multiples de 10
            if progress_percent % 10 == 0 and progress_percent != last_progress:
                self._safe_push_info(feedback, f"{progress_percent}% des entités traitées...")
                last_progress = progress_percent

            # affichage un message de finalisation une fois les 100% atteint
            # TODO : a DEBUG, ne s'affiche pas au bon moment
            if i + 1 == total_features:
                self._safe_push_info(feedback, "Finalisation du traitement en cours...")

        self._safe_push_info(feedback, f"Traitement finalisé : {nb_entites} entités traitées")
        return {self.OUTPUT: dest_id}
