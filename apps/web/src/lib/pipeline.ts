/**
 * The analysis stages in order, with their labels.
 *
 * Mirrors packages/real_estate/pipeline.py (STAGE_LIST); the backend test
 * tests/test_re_frontend_contract.py fails if the two drift apart.
 * GET /deals/pipeline-stages serves the same list.
 */
export const PIPELINE_STAGES: { agent_name: string; label: string }[] = [
  { agent_name: 'intake', label: 'Inventario documenti' },
  { agent_name: 'document_router', label: 'Classificazione documenti' },
  { agent_name: 'property_identity', label: "Identificazione dell'immobile" },
  { agent_name: 'title_chain_review', label: 'Provenienza' },
  { agent_name: 'encumbrances_review', label: 'Ipoteche e gravami' },
  { agent_name: 'building_cadastral_review', label: 'Urbanistica e catasto' },
  { agent_name: 'condominium_occupancy_review', label: 'Condominio e occupazione' },
  { agent_name: 'consistency_check', label: 'Confronto tra documenti' },
  { agent_name: 'red_flag_aggregation', label: 'Rilievi' },
  { agent_name: 'report_generation', label: 'Relazione' },
]

export const STAGE_LABELS: Record<string, string> = Object.fromEntries(
  PIPELINE_STAGES.map((stage) => [stage.agent_name, stage.label]),
)

export const TOTAL_STAGES = PIPELINE_STAGES.length

/** Stages whose results must exist before a report can be generated. */
export const REPORT_PREREQUISITES = PIPELINE_STAGES
  .map((stage) => stage.agent_name)
  .filter((name) => name !== 'report_generation')
