import logging
from dipper.utils.GraphUtils import GraphUtils
from dipper import curie_map

logger = logging.getLogger(__name__)


class Provenance:
    """
    To model provenance as the basis for an association.
    This encompasses:
        * Process history leading to a claim being made,
          including processes through which evidence is evaluated
        * Processes through which information used as evidence is created.

    Provenance metadata includes accounts of who conducted these processes,
     what entities participated in them, and when/where they occurred.

    """
    provenance_types = {
        'assay': 'OBI:0000070',
        'organization': 'foaf:organization',
        'person': GraphUtils.PERSON,
        'statistical_hypothesis_test': 'OBI:0000673',
        'mixed_model': 'STATO:0000189',
        'project': 'VIVO:Project',
        'study': 'OBI:0000471',
        'variant_classification_guideline': 'SEPIO:0000037',
        'assertion_process': 'SEPIO:0000003',
        'xref': 'OIO:hasdbxref'
    }

    object_properties = {
        'has_information_provenance': 'SEPIO:0000106',
        'has_participant': 'RO:0000057',
        'has_agent': 'SEPIO:0000017',
        'created_by_agent': 'SEPIO:0000018',
        'is_expressed_in': 'SEPIO:0000015',
        'output_of': 'RO:0002353',
        'specified_by': 'SEPIO:0000041',
        'created_at_location': 'SEPIO:0000019',
        'created_with_resource': 'SEPIO:0000022',
        'measures': 'SEPIO:measures'
    }

    def __init__(self, graph):

        self.graph = graph
        self.graph_utils = GraphUtils(curie_map.get())

        return

    def add_study_parts(self, study, study_parts):
        for part in study_parts:
            self.graph_utils.addTriple(self.graph, study,
                                       self.graph_utils.object_properties['part_of'],
                                       part)
        return

    def add_study_to_measurements(self, study, measurements):
        for measurement in measurements:
            self.graph_utils.addTriple(self.graph, measurement,
                                       self.object_properties['output_of'],
                                       study)
        return

    def add_study_measure(self, study, measure):
        self.graph_utils.addTriple(self.graph, study,
                                   self.object_properties['measures'],
                                   measure)
        return
    def add_agent_to_graph(self, agent_id, agent_label, agent_type=None,
                           agent_description=None):

        if agent_type is None:
            agent_type = self.provenance_types['organization']
        self.graph_utils.addIndividualToGraph(self.graph, agent_id,
                                              agent_label, agent_type,
                                              agent_description)

        return

    def add_assay_to_graph(self, assay_id, assay_label, assay_type=None,
                           assay_description=None):
        if assay_type is None:
            assay_type = self.provenance_types['assay']
        self.graph_utils.addIndividualToGraph(self.graph, assay_id,
                                              assay_label, assay_type,
                                              assay_description)

        return
