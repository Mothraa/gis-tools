# -*- coding: utf-8 -*-
"""
Area-weighted Sum - Prorata surfacique (somme)
compute Area-weighted sums of fields from an intersecting polygon layer.

Usage:
    - To load as a QGIS Processing script (toolbox)
    - See README.md and LICENSE.md for usage and license

"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Matthieu Lambert
# Author: Matthieu Lambert
# GitHub: https://github.com/Mothraa
# Issues: https://github.com/votre-utilisateur/nom-du-repo/issues
# Date: 2025-08-31
# Version: 0.1.0
# QGIS-Compatibility: QGIS 3.16+ (tested on 3.40)
# License: MIT (see LICENSE.md)

from qgis.PyQt.QtCore import QCoreApplication, QVariant # type: ignore
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingFeatureSource,
    QgsFeature,
    QgsField,
    QgsProcessingException, # type: ignore
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
            "Calcule un prorata surfacique (somme)"
            "d'une couche intersectante polygonale (ex : données statistiques au bâti, à l'IRIS,...) "
            "sur une couche principale polygonale (ex : zone de chalandise).\n"
            "Plusieurs champs peuvent être traités en même temps.\n"
            "Les champs doivent être dans un format numérique.\n"
            "Pour chaque entité de la couche principale :\n"
            "  • Le script cherche toutes les entités de la couche intersectante qui la "
            "chevauchent partiellement ou totalement.\n"
            "  • Il calcule la géométrie exacte de cette intersection.\n"
            "  • Les valeurs des champs choisis sont redistribuées proportionnellement "
            "à la surface intersectée (valeur * surface_intersection / surface_totale_intersectant).\n \n"
            "En sortie :\n"
            "  • une couche principale enrichie avec la somme des champs proratisés (suffix '_prorata'),\n"
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
            index.insertFeature(f)
        return index

    def prepareOutputFields(self, input_layer, fields_to_prorate):
        """ create proratized fields """
        output_fields = input_layer.fields()

        for f in fields_to_prorate:
            field_name = f"{f}_prorata"
            # verifie si le champ existe déjà
            if output_fields.indexFromName(field_name) == -1:
                # création du champ
                output_fields.append(QgsField(field_name, QVariant.Double, len=10, prec=5))
        return output_fields

    def _safe_push_info(self, feedback: QgsProcessingFeedback | None, message: str) -> None:
        """Safely push an info message to feedback"""
        if feedback is None:
            return
        try:
            feedback.pushInfo(message)
        except RuntimeError:
            return
        except Exception:
            return

    def _safe_is_canceled(self, feedback: QgsProcessingFeedback | None) -> bool:
        """Check if user want to cancel script execution"""
        if feedback is None:
            return False
        try:
            return feedback.isCanceled()
        except RuntimeError:
            return False
        except Exception:
            return False

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
        intersecting_feats = []

        if inter_ids:
            request = QgsFeatureRequest().setFilterFids(inter_ids)
            feature_iter = inter_layer.getFeatures(request)
            if feature_iter is not None:
                candidate_feat = QgsFeature()
                # nextFeature remplit candidate_feat et renvoie True tant qu'il y a des entités
                while feature_iter.nextFeature(candidate_feat):
                    # vérification de la géométrie et de l'intersection réelle
                    if candidate_feat.geometry() is not None and candidate_feat.geometry().intersects(geom):
                        # copie la feature pour la conserver
                        intersecting_feats.append(QgsFeature(candidate_feat))
        else:
            intersecting_feats = []

        # Init à 0 des champs proratisés
        prorata_values = {f: 0.0 for f in fields_to_prorate}

        # Bouclage sur les entités intersectées
        for inter in intersecting_feats:
            # Calcul de l'intersection géométrique exacte
            inter_geom = inter.geometry().intersection(geom)
            # Ignorer si intersection vide => cas spécifique, ne devrait pas se produire vu verif préalable
            if inter_geom is None or inter_geom.isEmpty():
                continue

            area = inter_geom.area()  # Surface de l'intersection
            inter_area = inter.geometry().area()  # Surface totale de l'entité intersectante

            if inter_area > 0:
                # Pour chaque champ, conversion en float et calcul du prorata
                # TODO : a refacto
                for field in fields_to_prorate:
                    raw = inter.attribute(field)  # obtenir la valeur d'attribut (type natif si possible)
                    if raw is None:
                        num = 0.0
                    else:
                        try:
                            num = float(raw)
                        except Exception:
                            # cas d'un QVariant
                            try:
                                num = float(raw.toDouble()[0])
                            except Exception:
                            # cas d'une string avec ','
                                try:
                                    num = float(str(raw).replace(",", "."))
                                except Exception:
                                    # si toujours NOK...
                                    num = 0.0
                    prorata_values[field] += num * area / inter_area

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

        input_layer = self.parameterAsSource(parameters, self.INPUT, context)
        inter_layer = self.parameterAsSource(parameters, self.INTERSECT, context)
        fields_to_prorate = self.parameterAsFields(parameters, self.FIELDS, context)

        if input_layer is None or inter_layer is None:
            raise QgsProcessingException("Impossible de charger la couche principale ou intersectante.")

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
        finalization_message_displayed = False

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

            # Affichage d'avancement tous les multiples de 10 %
            progress_percent = int((i + 1) / total_features * 100)
            if progress_percent % 10 == 0 and progress_percent != last_progress:
                self._safe_push_info(feedback, f"{progress_percent}% des entités traitées...")
                last_progress = progress_percent

            # affichage un message de finalisation une fois les 100% atteint
            if progress_percent == 100 and not finalization_message_displayed:
                self._safe_push_info(feedback, "Finalisation du traitement en cours...")
                finalization_message_displayed = True

        self._safe_push_info(feedback, f"Traitement finalisé : {nb_entites} entités traitées")
        return {self.OUTPUT: dest_id}