# filter.py (stewi)
# !/usr/bin/env python3
# coding=utf-8
"""
Functions to support filtering of processed inventories
"""

import pandas as pd
from stewi.globals import data_dir, import_table, config, read_inventory

filter_config = config(file = 'filter.yaml')

def apply_filter_to_inventory(inventory, inventory_acronym, year, filter_list):
    """Applies one or more filters from a passed list to an inventory dataframe
    :param inventory: df of stewi inventory of type flowbyfacility or flowbyprocess
    :param inventory_acronym: str of inventory e.g. 'NEI'
    :param year: year as number like 2010
    :param filter_list: a list of named filters to apply to inventory
    :return: DataFrame of filtered inventory    
    """

    if 'filter_for_LCI' in filter_list:
        for name in filter_config['filter_for_LCI']['filters']:
            if name not in filter_list:
                filter_list.append(name)

    if 'US_States_only' in filter_list:
        inventory = filter_states(inventory)

    if inventory_acronym == 'DMR':
        if 'remove_duplicate_organic_enrichment' in filter_list:
            from stewi.DMR import remove_duplicate_organic_enrichment
            inventory = remove_duplicate_organic_enrichment(inventory)

    if inventory_acronym == 'RCRAInfo':
        if 'National_Biennial_Report' in filter_list:
            fac_list = read_inventory('RCRAInfo', year, 'facility')
            fac_list = fac_list[['FacilityID',
                                 'Generator ID Included in NBR']
                                ].drop_duplicates(ignore_index = True)
            inventory = inventory.merge(fac_list, how = 'left')
            inventory = inventory[inventory['Generator ID Included in NBR'] == 'Y']
            inventory = inventory[inventory['Source Code'] != 'G61']
            inventory = inventory[inventory['Generator Waste Stream Included in NBR'] == 'Y']

        if 'imported_wastes' in filter_list:
            imp_source_codes = filter_config['imported_wastes']['source_codes']
            inventory = inventory[~inventory['Source Code'].isin(imp_source_codes)]

    if 'flows_for_LCI' in filter_list:
        flow_filter_list = filter_config['flows_for_LCI'][inventory_acronym]
        inventory = inventory[~inventory['FlowName'].isin(flow_filter_list)]
        
        # elif inventory_acronym == 'GHGRP':
        #     filter_path += 'ghg_mapping.csv'
        #     filter_type = 'keep'
        
    return inventory


def filter_states(inventory_df, include_states=True, include_dc=True,
                  include_territories=False):
    """Removes records from passed dataframe that are not included in the list of
    states
    :param inventory_df: dataframe that includes column 'State' of 2 digit strings
    :param include_states: bool, True to include data from 50 U.S. states
    :param include_dc: bool, True to include data from D.C.
    :param include_territories: bool, True to include data from U.S. territories
    :return: DataFrame
    """
    states_df = pd.read_csv(data_dir + 'state_codes.csv')
    states_list = []
    if include_states: states_list += list(states_df['states'].dropna())
    if include_dc: states_list += list(states_df['dc'].dropna())
    if include_territories: states_list += list(states_df['territories'].dropna())
    output_inventory = inventory_df[inventory_df['State'].isin(states_list)]
    return output_inventory

