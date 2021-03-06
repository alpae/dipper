import csv
import gzip
import re
import logging
import os
import json

from dipper.sources.Source import Source
from dipper.models.Genotype import Genotype
from dipper.models.Dataset import Dataset
from dipper.models.assoc.G2PAssoc import G2PAssoc
from dipper.models.Evidence import Evidence
from dipper.models.Provenance import Provenance
from dipper.models.Model import Model

logger = logging.getLogger(__name__)
IMPCDL = 'ftp://ftp.ebi.ac.uk/pub/databases/impc/latest/csv'


class IMPC(Source):
    """
    From the [IMPC](http://mousephenotype.org) website:
    The IMPC is generating a knockout mouse strain for every protein coding
    gene by using the embryonic stem cell resource generated by the
    International Knockout Mouse Consortium (IKMC).
    Systematic broad-based phenotyping is performed by each IMPC center using
    standardized procedures found within the
    International Mouse Phenotyping Resource of Standardised Screens (IMPReSS)
    resource. Gene-to-phenotype associations are made by a versioned
    statistical analysis with all data freely available by this web portal and
    by several data download features.

    Here, we pull the data and model the genotypes using GENO and the
    genotype-to-phenotype associations using the OBAN schema.

    We use all identifiers given by the IMPC with a few exceptions:

    *  For identifiers that IMPC provides, but does not resolve,
    we instantiate them as Blank Nodes.
    Examples include things with the pattern of: UROALL, EUROCURATE, NULL-*,

    *  We mint three identifiers:
    1.  Intrinsic genotypes not including sex, based on:
     * colony_id (ES cell line + phenotyping center)
     * strain
     * zygosity
    
    2.  For the Effective genotypes that are attached to the phenotypes:
     * colony_id (ES cell line + phenotyping center)
     * strain
     * zygosity
     * sex
    
    3.  Associations based on:
    effective_genotype_id + phenotype_id + phenotyping_center +
    pipeline_stable_id + procedure_stable_id + parameter_stable_id

    We DO NOT yet add the assays as evidence for the G2P associations here.
    To be added in the future.

    """

    files = {
        # 'impc': {
        #   'file': 'IMPC_genotype_phenotype.csv.gz',
        #   'url': IMPCDL + '/IMPC_genotype_phenotype.csv.gz'},
        # 'euro': {
        #   'file': 'EuroPhenome_genotype_phenotype.csv.gz',
        #   'url': IMPCDL + '/EuroPhenome_genotype_phenotype.csv.gz'},
        # 'mgd': {
        #   'file': 'MGP_genotype_phenotype.csv.gz',
        #   'url': IMPCDL + '/MGP_genotype_phenotype.csv.gz'},
        # '3i': {
        #   'file': '3I_genotype_phenotype.csv.gz',
        #   'url': IMPCDL + '/3I_genotype_phenotype.csv.gz'},
        'all': {
            'file': 'ALL_genotype_phenotype.csv.gz',
            'url': IMPCDL + '/ALL_genotype_phenotype.csv.gz'},
        'checksum': {
            'file': 'checksum.md5',
            'url': IMPCDL + '/checksum.md5'},
    }

    # Files that map IMPC codes to their IRIs, either generated manually
    # or by web crawling, see /scripts/README.md
    map_files = {
        # Procedures
        'impress_map': 'https://data.monarchinitiative.org/dipper/cache/impress_codes.json',
        # All other curated mappings
        'impc_map': '../../resources/impc_mappings.yaml'
    }

    # TODO move these into the conf.json
    # the following are gene ids for testing
    test_ids = [
        "MGI:109380", "MGI:1347004", "MGI:1353495", "MGI:1913840",
        "MGI:2144157", "MGI:2182928", "MGI:88456", "MGI:96704", "MGI:1913649",
        "MGI:95639", "MGI:1341847", "MGI:104848", "MGI:2442444", "MGI:2444584",
        "MGI:1916948", "MGI:107403", "MGI:1860086", "MGI:1919305",
        "MGI:2384936", "MGI:88135", "MGI:1913367", "MGI:1916571",
        "MGI:2152453", "MGI:1098270"]

    def __init__(self, graph_type, are_bnodes_skolemized):
        super().__init__(graph_type, are_bnodes_skolemized, 'impc')

        # update the dataset object with details about this resource
        self.dataset = Dataset(
            'impc', 'IMPC', 'http://www.mousephenotype.org', None,
            'https://raw.githubusercontent.com/mpi2/PhenotypeArchive/master/LICENSE')

        # TODO add a citation for impc dataset as a whole
        # :impc cito:citesAsAuthority PMID:24194600

        return

    def fetch(self, is_dl_forced=False):
        self.get_files(is_dl_forced)
        logger.info("Verifying checksums...")
        if self.compare_checksums():
            logger.debug('Files have same checksum as reference')
        else:
            raise Exception('Reference checksums do not match disk')
        return

    def parse(self, limit=None):
        """
        IMPC data is delivered in three separate csv files OR
        in one integrated file, each with the same file format.

        :param limit:
        :return:

        """
        if limit is not None:
            logger.info("Only parsing first %s rows fo each file", str(limit))

        logger.info("Parsing files...")

        if self.testOnly:
            self.testMode = True

        # for f in ['impc', 'euro', 'mgd', '3i']:
        for f in ['all']:
            file = '/'.join((self.rawdir, self.files[f]['file']))
            self._process_data(file, limit)

        logger.info("Finished parsing")

        return

    def _process_data(self, raw, limit=None):
        logger.info("Processing Data from %s", raw)

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph
        model = Model(g)
        geno = Genotype(g)
        line_counter = 0

        impc_map = self.open_and_parse_yaml(self.map_files['impc_map'])
        impress_map = json.loads(
            self.fetch_from_url(self.map_files['impress_map'])
            .read()
            .decode('utf-8'))

        # Add the taxon as a class
        taxon_id = 'NCBITaxon:10090'  # map to Mus musculus
        model.addClassToGraph(taxon_id, None)

        # with open(raw, 'r', encoding="utf8") as csvfile:
        with gzip.open(raw, 'rt') as csvfile:
            filereader = csv.reader(csvfile, delimiter=',', quotechar='\"')
            next(filereader, None)  # skip the header row
            for row in filereader:
                line_counter += 1

                (marker_accession_id, marker_symbol, phenotyping_center,
                 colony, sex, zygosity, allele_accession_id, allele_symbol,
                 allele_name, strain_accession_id, strain_name, project_name,
                 project_fullname, pipeline_name, pipeline_stable_id,
                 procedure_stable_id, procedure_name, parameter_stable_id,
                 parameter_name, top_level_mp_term_id, top_level_mp_term_name,
                 mp_term_id, mp_term_name, p_value, percentage_change,
                 effect_size, statistical_method, resource_name) = row

                if self.testMode and marker_accession_id not in self.test_ids:
                    continue

                # ##### cleanup some of the identifiers ######
                zygosity_id = self._map_zygosity(zygosity)

                # colony ids sometimes have <> in them, spaces,
                # or other non-alphanumerics and break our system;
                # replace these with underscores
                colony_id = '_:'+re.sub(r'\W+', '_', colony)

                if not re.match(r'MGI', allele_accession_id):
                    allele_accession_id = \
                        '_:IMPC-'+re.sub(r':', '', allele_accession_id)

                if re.search(r'EUROCURATE', strain_accession_id):
                    # the eurocurate links don't resolve at IMPC
                    strain_accession_id = '_:'+strain_accession_id

                elif not re.match(r'MGI', strain_accession_id):
                    logger.info(
                        "Found a strange strain accession...%s",
                        strain_accession_id)
                    strain_accession_id = 'IMPC:'+strain_accession_id

                ######################
                # first, add the marker and variant to the graph as with MGI,
                # the allele is the variant locus.  IF the marker is not known,
                # we will call it a sequence alteration.  otherwise,
                # we will create a BNode for the sequence alteration.
                sequence_alteration_id = variant_locus_id = None
                variant_locus_name = sequence_alteration_name = None

                # extract out what's within the <> to get the symbol
                if re.match(r'.*<.*>', allele_symbol):
                    sequence_alteration_name = \
                        re.match(r'.*<(.*)>', allele_symbol).group(1)
                else:
                    sequence_alteration_name = allele_symbol

                if marker_accession_id is not None and \
                        marker_accession_id == '':
                    logger.warning(
                        "Marker unspecified on row %d", line_counter)
                    marker_accession_id = None

                if marker_accession_id is not None:
                    variant_locus_id = allele_accession_id
                    variant_locus_name = allele_symbol
                    variant_locus_type = geno.genoparts['variant_locus']
                    geno.addGene(marker_accession_id, marker_symbol,
                                 geno.genoparts['gene'])
                    geno.addAllele(variant_locus_id, variant_locus_name,
                                   variant_locus_type, None)
                    geno.addAlleleOfGene(variant_locus_id, marker_accession_id)

                    sequence_alteration_id = \
                        '_:seqalt'+re.sub(r':', '', allele_accession_id)
                    geno.addSequenceAlterationToVariantLocus(
                        sequence_alteration_id, variant_locus_id)

                else:
                    sequence_alteration_id = allele_accession_id

                # IMPC contains targeted mutations with either gene traps,
                # knockouts, insertion/intragenic deletions.
                # but I don't really know what the SeqAlt is here,
                # so I don't add it.
                geno.addSequenceAlteration(sequence_alteration_id,
                                           sequence_alteration_name)

                # #############    BUILD THE COLONY    #############
                # First, let's describe the colony that the animals come from
                # The Colony ID refers to the ES cell clone
                #   used to generate a mouse strain.
                # Terry sez: we use this clone ID to track
                #   ES cell -> mouse strain -> mouse phenotyping.
                # The same ES clone maybe used at multiple centers,
                # so we have to concatenate the two to have a unique ID.
                # some useful reading about generating mice from ES cells:
                # http://ki.mit.edu/sbc/escell/services/details

                # here, we'll make a genotype
                # that derives from an ES cell with a given allele.
                # the strain is not really attached to the colony.

                # the colony/clone is reflective of the allele,
                # with unknown zygosity
                stem_cell_class = 'ERO:0002002'
                model.addIndividualToGraph(colony_id, colony, stem_cell_class)

                # vslc of the colony has unknown zygosity
                # note that we will define the allele
                # (and it's relationship to the marker, etc.) later
                # FIXME is it really necessary to create this vslc
                # when we always know it's unknown zygosity?
                vslc_colony = \
                    '_:'+re.sub(r':', '', allele_accession_id+geno.zygosity['indeterminate'])
                vslc_colony_label = allele_symbol+'/<?>'
                # for ease of reading, we make the colony genotype variables.
                # in the future, it might be desired to keep the vslcs
                colony_genotype_id = vslc_colony
                colony_genotype_label = vslc_colony_label
                geno.addGenotype(colony_genotype_id, colony_genotype_label)
                geno.addParts(allele_accession_id, colony_genotype_id,
                              geno.object_properties['has_alternate_part'])
                geno.addPartsToVSLC(
                    vslc_colony, allele_accession_id, None,
                    geno.zygosity['indeterminate'],
                    geno.object_properties['has_alternate_part'])
                g.addTriple(
                    colony_id,
                    geno.object_properties['has_genotype'],
                    colony_genotype_id)

                # ##########    BUILD THE ANNOTATED GENOTYPE    ##########
                # now, we'll build the genotype of the individual that derives
                # from the colony/clone genotype that is attached to
                # phenotype = colony_id + strain + zygosity + sex
                # (and is derived from a colony)

                # this is a sex-agnostic genotype
                genotype_id = \
                    self.make_id(
                        (colony_id + phenotyping_center + zygosity +
                         strain_accession_id))
                geno.addSequenceDerivesFrom(genotype_id, colony_id)

                # build the VSLC of the sex-agnostic genotype
                # based on the zygosity
                allele1_id = allele_accession_id
                allele2_id = allele2_rel = None
                allele1_label = allele_symbol
                allele2_label = '<?>'
                # Making VSLC labels from the various parts,
                # can change later if desired.
                if zygosity == 'heterozygote':
                    allele2_label = re.sub(r'<.*', '<+>', allele1_label)
                    allele2_id = None
                elif zygosity == 'homozygote':
                    allele2_label = allele1_label
                    allele2_id = allele1_id
                    allele2_rel = geno.object_properties['has_alternate_part']
                elif zygosity == 'hemizygote':
                    allele2_label = re.sub(r'<.*', '<0>', allele1_label)
                    allele2_id = None
                elif zygosity == 'not_applicable':
                    allele2_label = re.sub(r'<.*', '<?>', allele1_label)
                    allele2_id = None
                else:
                    logger.warning("found unknown zygosity %s", zygosity)
                    break
                vslc_name = '/'.join((allele1_label, allele2_label))

                # Add the VSLC
                vslc_id = '-'.join((marker_accession_id,
                                          allele_accession_id, zygosity))
                vslc_id = re.sub(r':', '', vslc_id)
                vslc_id = '_:'+vslc_id
                model.addIndividualToGraph(
                    vslc_id, vslc_name,
                    geno.genoparts['variant_single_locus_complement'])
                geno.addPartsToVSLC(
                    vslc_id, allele1_id, allele2_id, zygosity_id,
                    geno.object_properties['has_alternate_part'],
                    allele2_rel)

                # add vslc to genotype
                geno.addVSLCtoParent(vslc_id, genotype_id)

                # note that the vslc is also the gvc
                model.addType(
                    vslc_id,
                    Genotype.genoparts['genomic_variation_complement'])

                # Add the genomic background
                # create the genomic background id and name
                if strain_accession_id != '':
                    genomic_background_id = strain_accession_id
                else:
                    genomic_background_id = None

                genotype_name = vslc_name
                if genomic_background_id is not None:
                    geno.addGenotype(
                        genomic_background_id, strain_name,
                        geno.genoparts['genomic_background'])

                    # make a phenotyping-center-specific strain
                    # to use as the background
                    pheno_center_strain_label = \
                        strain_name + '-' + phenotyping_center + '-' + colony
                    pheno_center_strain_id = \
                        '-'.join((re.sub(r':', '', genomic_background_id),
                                  re.sub(r'\s', '_', phenotyping_center),
                                  re.sub(r'\W+', '', colony)))
                    if not re.match(r'^_', pheno_center_strain_id):
                        pheno_center_strain_id = '_:'+pheno_center_strain_id

                    geno.addGenotype(pheno_center_strain_id,
                                     pheno_center_strain_label,
                                     geno.genoparts['genomic_background'])
                    geno.addSequenceDerivesFrom(pheno_center_strain_id,
                                                genomic_background_id)

                    # Making genotype labels from the various parts,
                    # can change later if desired.
                    # since the genotype is reflective of the place
                    # it got made, should put that in to disambiguate
                    genotype_name = \
                        genotype_name+' ['+pheno_center_strain_label+']'
                    geno.addGenomicBackgroundToGenotype(
                        pheno_center_strain_id, genotype_id)
                    geno.addTaxon(taxon_id, pheno_center_strain_id)
                # this is redundant, but i'll keep in in for now
                geno.addSequenceDerivesFrom(genotype_id, colony_id)
                geno.addGenotype(genotype_id, genotype_name)

                # Make the sex-qualified genotype,
                # which is what the phenotype is associated with
                sex_qualified_genotype_id = \
                    self.make_id(
                        (colony_id + phenotyping_center + zygosity +
                         strain_accession_id+sex))
                sex_qualified_genotype_label = genotype_name+' ('+sex+')'
                if sex == 'male':
                    sq_type_id = geno.genoparts['male_genotype']
                elif sex == 'female':
                    sq_type_id = geno.genoparts['female_genotype']
                else:
                    sq_type_id = geno.genoparts['sex_qualified_genotype']

                geno.addGenotype(
                    sex_qualified_genotype_id,
                    sex_qualified_genotype_label, sq_type_id)
                geno.addParts(
                    genotype_id, sex_qualified_genotype_id,
                    geno.object_properties['has_alternate_part'])

                if genomic_background_id is not None and \
                        genomic_background_id != '':
                    # Add the taxon to the genomic_background_id
                    geno.addTaxon(taxon_id, genomic_background_id)
                else:
                    # add it as the genomic background
                    geno.addTaxon(taxon_id, genotype_id)

                # #############    BUILD THE G2P ASSOC    #############
                # from an old email dated July 23 2014:
                # Phenotypes associations are made to
                # imits colony_id+center+zygosity+gender

                phenotype_id = mp_term_id

                # it seems that sometimes phenotype ids are missing.
                # indicate here
                if phenotype_id is None or phenotype_id == '':
                    logger.warning(
                        "No phenotype id specified for row %d: %s",
                        line_counter, str(row))
                    continue
                # hard coded ECO code
                eco_id = "ECO:0000015"

                # the association comes as a result of a g2p from
                # a procedure in a pipeline at a center and parameter tested

                assoc = G2PAssoc(g, self.name, sex_qualified_genotype_id,
                                 phenotype_id)
                assoc.add_evidence(eco_id)
                # assoc.set_score(float(p_value))

                # TODO add evidence instance using
                # pipeline_stable_id +
                # procedure_stable_id +
                # parameter_stable_id

                assoc.add_association_to_graph()
                assoc_id = assoc.get_association_id()

                # add a free-text description
                try:
                    description = \
                        ' '.join((mp_term_name, 'phenotype determined by',
                                  phenotyping_center, 'in an',
                                  procedure_name, 'assay where',
                                  parameter_name.strip(),
                                  'was measured with an effect_size of',
                                  str(round(float(effect_size), 5)),
                                  '(p =', "{:.4e}".format(float(p_value)), ').'))
                except ValueError:
                    description = \
                        ' '.join((mp_term_name, 'phenotype determined by',
                                  phenotyping_center, 'in an',
                                  procedure_name, 'assay where',
                                  parameter_name.strip(),
                                  'was measured with an effect_size of',
                                  str(effect_size),
                                  '(p =', "{0}".format(p_value), ').'))

                study_bnode = \
                    self._add_study_provenance(
                        impc_map, impress_map, phenotyping_center, colony,
                        project_fullname, pipeline_name, pipeline_stable_id,
                        procedure_stable_id, procedure_name,
                        parameter_stable_id, parameter_name,
                        statistical_method, resource_name)

                evidence_line_bnode = \
                    self._add_evidence(
                        assoc_id, eco_id, impc_map, p_value, percentage_change,
                        effect_size, study_bnode)

                self._add_assertion_provenance(assoc_id,
                                               evidence_line_bnode, impc_map)

                model.addDescription(evidence_line_bnode, description)

                # resource_id = resource_name
                # assoc.addSource(g, assoc_id, resource_id)

                if not self.testMode and \
                        limit is not None and line_counter > limit:
                    break

        return

    @staticmethod
    def _map_zygosity(zygosity):
        typeid = Genotype.zygosity['indeterminate']
        type_map = {
            'heterozygote': Genotype.zygosity['simple_heterozygous'],
            'homozygote': Genotype.zygosity['homozygous'],
            'hemizygote': Genotype.zygosity['hemizygous'],
            'not_applicable': Genotype.zygosity['indeterminate']
        }
        if zygosity.strip() in type_map:
            typeid = type_map.get(zygosity)
        else:
            logger.warning("Zygosity type not mapped: %s", zygosity)
        return typeid

    def _add_assertion_provenance(
            self, assoc_id, evidence_line_bnode, impc_map):
        """
        Add assertion level provenance, currently always IMPC
        :param assoc_id:
        :param evidence_line_bnode:
        :return:
        """
        provenance_model = Provenance(self.graph)
        model = Model(self.graph)
        assertion_bnode = self.make_id("assertion{0}{1}".format(
            assoc_id, impc_map['asserted_by']['IMPC']),  '_')

        model.addIndividualToGraph(
            assertion_bnode, None,
            provenance_model.provenance_types['assertion'])

        provenance_model.add_assertion(
            assertion_bnode, impc_map['asserted_by']['IMPC'],
            'International Mouse Phenotyping Consortium')

        self.graph.addTriple(
            assoc_id, provenance_model.object_properties['is_asserted_in'],
            assertion_bnode)

        self.graph.addTriple(
            assertion_bnode,
            provenance_model.object_properties['is_assertion_supported_by'],
            evidence_line_bnode)

        return

    def _add_study_provenance(self, impc_map, impress_map,
                              phenotyping_center, colony, project_fullname,
                              pipeline_name, pipeline_stable_id,
                              procedure_stable_id, procedure_name,
                              parameter_stable_id, parameter_name,
                              statistical_method, resource_name):
        """
        :param impc_map: dict, generated from map file
        see self._get_impc_mappings() docstring
        :param impress_map: dict, generated from map file
        see _get_impress_mappings() docstring
        :param phenotyping_center: str, from self.files['all']
        :param colony: str, from self.files['all']
        :param project_fullname: str, from self.files['all']
        :param pipeline_name: str, from self.files['all']
        :param pipeline_stable_id: str, from self.files['all']
        :param procedure_stable_id: str, from self.files['all']
        :param procedure_name: str, from self.files['all']
        :param parameter_stable_id: str, from self.files['all']
        :param parameter_name: str, from self.files['all']
        :param statistical_method: str, from self.files['all']
        :param resource_name: str, from self.files['all']
        :return: study bnode
        """

        provenance_model = Provenance(self.graph)
        model = Model(self.graph)

        # Add provenance
        # A study is a blank node equal to its parts
        study_bnode = self.make_id("{0}{1}{2}{3}{4}{5}{6}{7}".format(
            phenotyping_center, colony, project_fullname, pipeline_stable_id,
            procedure_stable_id, parameter_stable_id, statistical_method,
            resource_name), '_')

        model.addIndividualToGraph(
            study_bnode, None,
            provenance_model.provenance_types['study'])

        # List of nodes linked to study with has_part property
        study_parts = []

        # Add study parts
        model.addIndividualToGraph(
            impress_map[procedure_stable_id],
            procedure_name)
        study_parts.append(impress_map[procedure_stable_id])

        study_parts.append(
            impc_map['statistical_method'][statistical_method])
        provenance_model.add_study_parts(study_bnode, study_parts)

        # Add parameter/measure statement: study measures parameter
        parameter_label = "{0} ({1})".format(parameter_name, procedure_name)
        model.addIndividualToGraph(
            impress_map[parameter_stable_id], parameter_label)
        provenance_model.add_study_measure(
            study_bnode, impress_map[parameter_stable_id])

        # Add Colony
        colony_bnode = self.make_id("{0}".format(colony), '_')
        model.addIndividualToGraph(colony_bnode, colony)

        # Add study agent
        model.addIndividualToGraph(
            impc_map['phenotyping_center'][phenotyping_center],
            phenotyping_center,
            provenance_model.provenance_types['organization'])
        self.graph.addTriple(
            study_bnode,
            provenance_model.object_properties['has_agent'],
            impc_map['phenotyping_center'][phenotyping_center])

        # add pipeline and project
        model.addIndividualToGraph(
            impress_map[pipeline_stable_id],
            pipeline_name)

        self.graph.addTriple(
            study_bnode, model.object_properties['part_of'],
            impress_map[pipeline_stable_id])

        model.addIndividualToGraph(
            impc_map['project'][project_fullname],
            project_fullname, provenance_model.provenance_types['project'])
        self.graph.addTriple(
            study_bnode, model.object_properties['part_of'],
            impc_map['project'][project_fullname])

        return study_bnode

    def _add_evidence(self, assoc_id, eco_id, impc_map, p_value,
                      percentage_change, effect_size, study_bnode):
        """
        :param assoc_id: assoc curie used to reify a
        genotype to phenotype association, generated in _process_data()
        :param eco_id: eco_id as curie, hardcoded in _process_data()
        :param impc_map: dict, generated from map file
        see self._get_impc_mappings() docstring
        :param p_value: str, from self.files['all']
        :param percentage_change: str, from self.files['all']
        :param effect_size: str, from self.files['all']
        :param study_bnode: str, from self.files['all']
        :param phenotyping_center: str, from self.files['all']
        :return: str, evidence_line_bnode as curie
        """

        evidence_model = Evidence(self.graph, assoc_id)
        provenance_model = Provenance(self.graph)
        model = Model(self.graph)

        # Add line of evidence
        evidence_line_bnode = self.make_id(
            "{0}{1}".format(assoc_id, study_bnode), '_')
        evidence_model.add_supporting_evidence(evidence_line_bnode)
        model.addIndividualToGraph(evidence_line_bnode, None, eco_id)

        # Add supporting measurements to line of evidence
        measurements = {}
        if p_value is not None or p_value != "":
            p_value_bnode = self.make_id("{0}{1}{2}"
                                         .format(evidence_line_bnode,
                                                 'p_value', p_value), '_')
            model.addIndividualToGraph(p_value_bnode, None,
                                       impc_map['measurements']['p_value'])
            try:
                measurements[p_value_bnode] = float(p_value)
            except ValueError:
                measurements[p_value_bnode] = p_value
        if percentage_change is not None and percentage_change != '':

            fold_change_bnode = self.make_id(
                "{0}{1}{2}".format(
                    evidence_line_bnode, 'percentage_change',
                    percentage_change), '_')
            model.addIndividualToGraph(
                fold_change_bnode, None,
                impc_map['measurements']['percentage_change'])
            measurements[fold_change_bnode] = percentage_change
        if effect_size is not None or effect_size != "":
            fold_change_bnode = self.make_id(
                "{0}{1}{2}".format(
                    evidence_line_bnode, 'effect_size', effect_size), '_')
            model.addIndividualToGraph(
                fold_change_bnode, None,
                impc_map['measurements']['effect_size'])
            measurements[fold_change_bnode] = effect_size

        evidence_model.add_supporting_data(evidence_line_bnode, measurements)

        # Link evidence to provenance by connecting to study node
        provenance_model.add_study_to_measurements(
            study_bnode, measurements.keys())
        self.graph.addTriple(
            evidence_line_bnode,
            provenance_model.object_properties['has_supporting_study'],
            study_bnode)

        return evidence_line_bnode

    def parse_checksum_file(self, file):
        """
        :param file
        :return dict

        """
        checksums = dict()
        file_path = '/'.join((self.rawdir, file))
        with open(file_path, 'rt') as tsvfile:
            reader = csv.reader(tsvfile, delimiter=' ')
            for row in reader:
                (checksum, whitespace, file_name) = row
                checksums[checksum] = file_name

        return checksums

    def compare_checksums(self):
        """
        test to see if fetched file matches checksum from ebi
        :return: True or False

        """
        is_match = True
        reference_checksums = self.parse_checksum_file(
            self.files['checksum']['file'])
        for md5, file in reference_checksums.items():
            if os.path.isfile('/'.join((self.rawdir, file))):
                if self.get_file_md5(self.rawdir, file) != md5:
                    is_match = False
                    logger.warning('%s was not downloaded completely', file)
                    return is_match

        return is_match

    def getTestSuite(self):
        import unittest
        from tests.test_impc import IMPCTestCase
        # TODO test genotypes

        test_suite = unittest.TestLoader().loadTestsFromTestCase(IMPCTestCase)

        return test_suite
