# validate.py (stewi)
# !/usr/bin/env python3
# coding=utf-8
"""
Functions to support validation of generated inventories
"""
import pandas as pd
import numpy as np
from datetime import datetime

from esupy.processed_data_mgmt import create_paths_if_missing
from stewi.globals import log, data_dir, paths, write_metadata,\
    source_metadata


def validate_inventory(inventory_df, reference_df, group_by='flow',
                       tolerance=5.0, filepath=''):
    """Compare inventory output with a reference DataFrame from another source.

    :param inventory_df: DataFrame of inventory resulting from script output
    :param reference_df: Reference DataFrame to compare emission quantities against.
        Must have same keys as inventory_df
    :param group_by: 'flow' for species summed across facilities, 'facility'
        to check species by facility
    :param tolerance: Maximum acceptable percent difference between inventory
        and reference values. Default is 5%
    :return: DataFrame containing 'Conclusion' of statistical comparison and
        'Percent_Difference'
    """
    if pd.api.types.is_string_dtype(inventory_df['FlowAmount']):
        inventory_df['FlowAmount'] = inventory_df['FlowAmount'].str.replace(',', '')
        inventory_df['FlowAmount'] = pd.to_numeric(inventory_df['FlowAmount'])
    if pd.api.types.is_string_dtype(reference_df['FlowAmount']):
        reference_df['FlowAmount'] = reference_df['FlowAmount'].str.replace(',', '')
        reference_df['FlowAmount'] = pd.to_numeric(reference_df['FlowAmount'])
    if group_by == 'flow':
        group_by_columns = ['FlowName']
        if 'Compartment' in inventory_df.keys():
            group_by_columns += ['Compartment']
    elif group_by == 'state':
        group_by_columns = ['State']
    elif group_by == 'facility':
        group_by_columns = ['FlowName', 'FacilityID']
    elif group_by == 'subpart':
        group_by_columns = ['FlowName', 'SubpartName']
    inventory_df['FlowAmount'] = inventory_df['FlowAmount'].fillna(0.0)
    reference_df['FlowAmount'] = reference_df['FlowAmount'].fillna(0.0)
    inventory_sums = inventory_df[group_by_columns + ['FlowAmount']].groupby(
        group_by_columns).sum().reset_index()
    reference_sums = reference_df[group_by_columns + ['FlowAmount']].groupby(
        group_by_columns).sum().reset_index()
    if filepath:
        reference_sums.to_csv(filepath, index=False)
    validation_df = inventory_sums.merge(reference_sums, how='outer',
                                         on=group_by_columns).reset_index(drop=True)
    validation_df = validation_df.fillna(0.0)
    amount_x_list = []
    amount_y_list = []
    pct_diff_list = []
    conclusion = []
    error_count = 0
    for index, row in validation_df.iterrows():
        amount_x = float(row['FlowAmount_x'])
        amount_y = float(row['FlowAmount_y'])
        if amount_x == 0.0:
            amount_x_list.append(amount_x)
            if amount_y == 0.0:
                pct_diff_list.append(0.0)
                amount_y_list.append(amount_y)
                conclusion.append('Both inventory and reference are zero or null')
            elif amount_y == np.inf:
                amount_y_list.append(np.nan)
                pct_diff_list.append(100.0)
                conclusion.append('Reference contains infinity values. '
                                  'Check prior calculations.')
            else:
                amount_y_list.append(amount_y)
                pct_diff_list.append(100.0)
                conclusion.append('Inventory value is zero or null')
                error_count += 1
            continue
        elif amount_y == 0.0:
            amount_x_list.append(amount_x)
            amount_y_list.append(amount_y)
            pct_diff_list.append(100.0)
            conclusion.append('Reference value is zero or null')
            continue
        elif amount_y == np.inf:
            amount_x_list.append(amount_x)
            amount_y_list.append(np.nan)
            pct_diff_list.append(100.0)
            conclusion.append('Reference contains infinity values. '
                              'Check prior calculations.')
        else:
            pct_diff = 100.0 * abs(amount_y - amount_x) / amount_y
            pct_diff_list.append(pct_diff)
            amount_x_list.append(amount_x)
            amount_y_list.append(amount_y)
            if pct_diff == 0.0:
                conclusion.append('Identical')
            elif pct_diff <= tolerance:
                conclusion.append('Statistically similar')
            elif pct_diff > tolerance:
                conclusion.append('Percent difference exceeds tolerance')
                error_count += 1
    validation_df['Inventory_Amount'] = amount_x_list
    validation_df['Reference_Amount'] = amount_y_list
    validation_df['Percent_Difference'] = pct_diff_list
    validation_df['Conclusion'] = conclusion
    validation_df = validation_df.drop(['FlowAmount_x', 'FlowAmount_y'], axis=1)
    if error_count > 0:
        log.warning(f'{str(error_count)} potential issues in validation '
                    'exceeding tolerance')

    return validation_df


def read_ValidationSets_Sources():
    """Read and return ValidationSets_Sources.csv file."""
    df = pd.read_csv(data_dir + 'ValidationSets_Sources.csv', header=0,
                     dtype={"Year": "str"})
    return df


def write_validation_result(inventory_acronym, year, validation_df):
    """Write the validation result and associated metadata to local dir.

    :param inventory_acronym: str for inventory e.g. 'TRI'
    :param year: str for year e.g. '2016'
    :param validation_df: df returned from validate_inventory function
    """
    directory = paths.local_path + '/validation/'
    create_paths_if_missing(directory)
    log.info(f'writing validation result to {directory}')
    validation_df.to_csv(directory + inventory_acronym + '_' + year + '.csv',
                         index=False)
    # Get metadata on validation dataset
    validation_set_info_table = read_ValidationSets_Sources()
    # Get record for year and source
    validation_set_info = validation_set_info_table[
        (validation_set_info_table['Inventory'] == inventory_acronym) &
        (validation_set_info_table['Year'] == year)]
    if len(validation_set_info) != 1:
        log.error('no validation metadata found')
        return
    # Convert to Series
    validation_set_info = validation_set_info.iloc[0, ]
    # Use the same format an inventory metadata to described the validation set data
    validation_metadata = dict(source_metadata)
    validation_metadata['SourceFileName'] = validation_set_info['Name']
    validation_metadata['SourceVersion'] = validation_set_info['Version']
    validation_metadata['SourceURL'] = validation_set_info['URL']
    validation_metadata['SourceAcquisitionTime'] = validation_set_info['Date Acquired']
    validation_metadata['Criteria'] = validation_set_info['Criteria']
    # Write metadata to file
    write_metadata(inventory_acronym + '_' + year, validation_metadata,
                   datatype="validation")


def update_validationsets_sources(validation_dict, date_acquired=False):
    """Add or replaces metadata dictionary of validation reference dataset to
    the validation sets sources file.

    :param validation_dict: dictionary of validation metadata
    :param date_acquired:
    """
    if not date_acquired:
        date = datetime.today().strftime('%d-%b-%Y')
        validation_dict['Date Acquired'] = date
    v_table = read_ValidationSets_Sources()
    existing = v_table.loc[(v_table['Inventory'] == validation_dict['Inventory']) &
                           (v_table['Year'] == validation_dict['Year'])]
    if len(existing) > 0:
        i = existing.index[0]
        v_table = v_table.loc[~v_table.index.isin(existing.index)]
        line = pd.DataFrame.from_records([validation_dict], index=[(i)])
    else:
        inventories = list(v_table['Inventory'])
        i = max(loc for loc, val in enumerate(inventories)
                if val == validation_dict['Inventory'])
        line = pd.DataFrame.from_records([validation_dict], index=[(i+0.5)])
    v_table = v_table.append(line, ignore_index=False)
    v_table = v_table.sort_index().reset_index(drop=True)
    log.info("updating ValidationSets_Sources.csv with ",
             f"{validation_dict['Inventory']} {validation_dict['Year']}")
    v_table.to_csv(data_dir + 'ValidationSets_Sources.csv', index=False)
