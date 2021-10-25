# eGRID.py (stewi)
# !/usr/bin/env python3
# coding=utf-8
"""
Imports eGRID data and processes to Standardized EPA output format.
Uses the eGRID data files from EPA.
This file requires parameters be passed like:

    Option -Y Year

Options:
    A - Download eGRID data
    B - Process and parse eGRID data and validation against national totals
    C - Download and process data for validation

Year:
    2019
    2018
    2016
    2014
"""

import pandas as pd
import argparse
import os
import zipfile
import io

from esupy.remote import make_http_request
from stewi.globals import data_dir, write_metadata,\
    unit_convert, log, MMBtu_MJ, MWh_MJ, config, USton_kg, lb_kg,\
    compile_source_metadata, remove_line_breaks, paths, store_inventory,\
    read_source_metadata, set_stewi_meta, get_optional_fields, aggregate
from stewi.validate import update_validationsets_sources, validate_inventory,\
    write_validation_result


_config = config()['databases']['eGRID']

# set filepath
ext_folder = 'eGRID Data Files'
eGRIDfilepath = paths.local_path + '/' + ext_folder + '/'
eGRID_data_dir = data_dir + 'eGRID/'


def imp_fields(fields_txt, year):
    """Import list of fields from egrid that are desired for LCI.

    :param fields_txt: str name of csv file
    :param year: str year of egrid inventory
    :return: a list of source fields and a dictionary to stewi fields
    """
    egrid_req_fields_df = pd.read_csv(eGRID_data_dir + fields_txt, header=0)
    egrid_req_fields_df = remove_line_breaks(egrid_req_fields_df,
                                             headers_only=False)
    egrid_req_fields = list(egrid_req_fields_df[year])
    col_dict = egrid_req_fields_df.set_index(year).to_dict()
    return egrid_req_fields, col_dict


def filter_fields(fields_txt, field):
    """Return a list of fields that are marked in the field column.

    :param fields_txt: str name of csv file
    :param field: str column to filter
    """
    egrid_req_fields_df = pd.read_csv(eGRID_data_dir + fields_txt, header=0)
    egrid_req_fields_df = remove_line_breaks(egrid_req_fields_df,
                                             headers_only=False)
    egrid_req_fields_df = egrid_req_fields_df[
        egrid_req_fields_df[field] == 1].reset_index(drop=True)
    egrid_req_fields = list(egrid_req_fields_df['StEWI'])
    return egrid_req_fields


def egrid_unit_convert(value, factor):
    new_val = value * factor
    return new_val


def download_eGRID(year):
    """Download eGRID files from EPA website."""
    log.info(f'downloading eGRID data for {year}')

    download_url = _config[year]['download_url']
    egrid_file_name = _config[year]['file_name']

    r = make_http_request(download_url)

    # extract .xlsx workbook
    if year == '2016' or year == '2014':
        z = zipfile.ZipFile(io.BytesIO(r.content))
        workbook = z.read(egrid_file_name)
    else:
        workbook = r.content

    # save .xlsx workbook to destination directory
    destination = eGRIDfilepath + egrid_file_name
    # if destination folder does not already exist, create it
    if not(os.path.exists(eGRIDfilepath)):
        os.makedirs(eGRIDfilepath)
    with open(destination, 'wb') as output:
        output.write(workbook)
    log.info(f'{egrid_file_name} saved to {eGRIDfilepath}')


def generate_metadata(year, datatype='inventory'):
    """Generate metadata and writes to json for datatypes 'inventory' or 'source'."""
    if datatype == 'source':
        source_path = eGRIDfilepath + _config[year]['file_name']
        source_meta = compile_source_metadata(source_path, _config, year)
        write_metadata('eGRID_' + year, source_meta, category=ext_folder,
                       datatype='source')
    else:
        source_meta = read_source_metadata(paths, set_stewi_meta('eGRID_' + year,
                                           ext_folder),
                                           force_JSON=True)['tool_meta']
        write_metadata('eGRID_' + year, source_meta, datatype=datatype)


def extract_eGRID_excel(year, sheetname, index='field'):
    """Generate a dataframe from eGRID sheetname from file stored locally."""
    eGRIDfile = eGRIDfilepath + _config[year]['file_name']
    if index != 'field': header = 1
    else: header = 0
    df = pd.read_excel(eGRIDfile, sheet_name=sheetname + year[2:],
                       header=header, engine='openpyxl')
    df = remove_line_breaks(df)
    if index == 'field':
        # drop first row which are column name abbreviations
        df = df.drop([0])
    return df


def parse_eGRID(year, sheetname, fields_txt):
    """Prepare eGRID sheet for processing."""
    egrid = extract_eGRID_excel(year, sheetname)
    # get list of columns not in the required fields and drop them
    required_fields, col_dict = imp_fields(fields_txt, year)
    colstodrop = list(set(list(egrid.columns)) - set(required_fields))
    egrid = egrid.drop(colstodrop, axis=1)
    egrid.rename(columns=col_dict['StEWI'], inplace=True)
    return egrid


def generate_eGRID_files(year):
    """Parse a local eGRID file to generate StEWI output files.

    :param year: str, Year of eGRID dataset
    """
    log.info(f'generating eGRID files for {year}')
    log.info('importing plant level emissions data')
    egrid = parse_eGRID(year, 'PLNT', 'eGRID_required_fields.csv')

    flowbyfac_fields = filter_fields('eGRID_required_fields.csv', 'flowbyfac_fields')

    flowbyfac_prelim = egrid[flowbyfac_fields]
    conversion = []
    conversion.append(flowbyfac_prelim[['FacilityID', 'Plant primary fuel']])
    conversion.append(egrid_unit_convert(
        flowbyfac_prelim[['Nitrogen oxides', 'Sulfur dioxide', 'Carbon dioxide']], USton_kg))
    conversion.append(egrid_unit_convert(
        flowbyfac_prelim[['Methane', 'Nitrous oxide']], lb_kg))
    conversion.append(egrid_unit_convert(
        flowbyfac_prelim[['Heat', 'Steam']], MMBtu_MJ))
    conversion.append(egrid_unit_convert(flowbyfac_prelim[['Electricity']], MWh_MJ))
    flowbyfac_stacked = pd.concat(conversion, axis=1)
    # Create flowbyfac
    flowbyfac = pd.melt(flowbyfac_stacked,
                        id_vars=['FacilityID', 'Plant primary fuel'],
                        value_vars=list(flowbyfac_stacked.columns[2:]),
                        var_name='FlowName', value_name='FlowAmount')

    flowbyfac = flowbyfac.dropna(subset=['FlowAmount'])
    flowbyfac['FlowAmount'] = pd.to_numeric(flowbyfac['FlowAmount'])
    flowbyfac = flowbyfac.sort_values(by=['FacilityID'], axis=0,
                                      ascending=True, inplace=False,
                                      kind='quicksort', na_position='last')

    # Read in unit sheet to get comment fields related to source of heat, NOx,
    # SO2, and CO2 emission estimates for calculating data quality information
    log.info('importing unit level data to assess data quality')
    unit_egrid = parse_eGRID(year, 'UNT', 'eGRID_unit_level_required_fields.csv')

    rel_score_cols = filter_fields('eGRID_unit_level_required_fields.csv',
                                   'reliability_flows')

    flows_used_for_weighting = filter_fields('eGRID_unit_level_required_fields.csv',
                                             'weighting_flows')

    unit_emissions_with_rel_scores = ['Heat', 'Nitrogen oxides',
                                      'Sulfur dioxide', 'Carbon dioxide']

    unit_egrid.update(unit_egrid[rel_score_cols].fillna(''))
    unit_egrid.update(unit_egrid[flows_used_for_weighting].fillna(0))
    # Generate combined columns as lists before exploding lists into multiple rows
    unit_egrid['FlowName'] = unit_egrid.apply(lambda _: unit_emissions_with_rel_scores, axis=1)
    unit_egrid['ReliabilitySource'] = unit_egrid[rel_score_cols].values.tolist()
    unit_egrid['FlowAmount'] = unit_egrid[flows_used_for_weighting].values.tolist()
    unit_egrid = unit_egrid.drop(columns=rel_score_cols + flows_used_for_weighting)
    unit_egrid = unit_egrid.set_index(list(
        unit_egrid.columns.difference(['FlowName', 'ReliabilitySource', 'FlowAmount']))
        ).apply(pd.Series.explode).reset_index()

    dq_mapping = pd.read_csv(
        eGRID_data_dir + 'eGRID_unit_level_reliability_scores.csv')
    unit_egrid = unit_egrid.merge(dq_mapping, how='left')

    # Aggregate data reliability scores by facility and flow
    rel_scores_by_facility = aggregate(unit_egrid, grouping_vars=['FacilityID', 'FlowName'])
    rel_scores_by_facility = rel_scores_by_facility.drop(columns=['FlowAmount'])

    # Merge in heat_SO2_CO2_NOx reliability scores calculated from unit sheet
    flowbyfac = flowbyfac.merge(rel_scores_by_facility,
                                on=['FacilityID', 'FlowName'], how='left')
    # Assign electricity to a reliabilty score of 1
    flowbyfac.loc[flowbyfac['FlowName'] == 'Electricity', 'DataReliability'] = 1
    flowbyfac['DataReliability'] = flowbyfac['DataReliability'].fillna(5)

    # Methane and nitrous oxide reliability scores
    # Assign 3 to all facilities except for certain fuel types where
    # measurements are taken
    flowbyfac.loc[(flowbyfac['FlowName'] == 'Methane') |
                  (flowbyfac['FlowName'] == 'Nitrous oxide'),
                  'DataReliability'] = 3
    # For all but selected fuel types, change it to 2
    flowbyfac.loc[((flowbyfac['FlowName'] == 'Methane') |
                   (flowbyfac['FlowName'] == 'Nitrous oxide')) &
                   ((flowbyfac['Plant primary fuel'] != 'PG') |
                    (flowbyfac['Plant primary fuel'] != 'RC') |
                    (flowbyfac['Plant primary fuel'] != 'WC') |
                    (flowbyfac['Plant primary fuel'] != 'SLW')),
                   'DataReliability'] = 2

    # Import flow compartments
    flow_compartments = pd.read_csv(eGRID_data_dir + 'eGRID_flow_compartments.csv',
                                    header=0)
    flowbyfac = pd.merge(flowbyfac, flow_compartments, on='FlowName', how='left')

    # Drop unneeded columns
    flowbyfac = flowbyfac.drop(columns=['Plant primary fuel', 'OriginalName'])

    # Write flowbyfacility file to output
    store_inventory(flowbyfac, 'eGRID_' + year, 'flowbyfacility')

    # Creation of the facility file
    # Need to change column names manually
    fac_fields = get_optional_fields('facility')
    fac_fields = list(fac_fields.keys())
    egrid_fields = filter_fields('eGRID_required_fields.csv', 'facility_fields')
    egrid_fac_fields = [c for c in egrid if c in (egrid_fields + fac_fields)]

    facility = egrid[egrid_fac_fields].reset_index(drop=True)

    # Data starting in 2018 for resource mix is listed as percentage.
    # For consistency multiply by 100
    if int(year) >= 2018:
        facility.loc[:, facility.columns.str.contains('resource mix')] *= 100

    log.debug(len(facility))
    #2019: 11865
    #2018: 10964
    #2016: 9709
    #2014: 8503
    store_inventory(facility, 'eGRID_' + year, 'facility')

    # Write flows file
    flows = flowbyfac[['FlowName', 'Compartment', 'Unit']]
    flows = flows.drop_duplicates()
    flows = flows.sort_values(by='FlowName', axis=0)
    store_inventory(flows, 'eGRID_' + year, 'flow')

    validate_eGRID(year, flowbyfac)


def validate_eGRID(year, flowbyfac):
    """Validate eGRID flowbyfacility data against national totals."""
    validation_file = data_dir + 'eGRID_' + year + '_NationalTotals.csv'
    if not(os.path.exists(validation_file)):
        generate_national_totals(year)
    log.info('validating data against national totals')
    egrid_national_totals = pd.read_csv(validation_file, header=0,
                                        dtype={"FlowAmount": float})
    egrid_national_totals = unit_convert(
        egrid_national_totals, 'FlowAmount', 'Unit', 'lbs',
        lb_kg, 'FlowAmount')
    egrid_national_totals = unit_convert(
        egrid_national_totals, 'FlowAmount', 'Unit', 'tons',
        USton_kg, 'FlowAmount')
    egrid_national_totals = unit_convert(
        egrid_national_totals, 'FlowAmount', 'Unit', 'MMBtu',
        MMBtu_MJ, 'FlowAmount')
    egrid_national_totals = unit_convert(
        egrid_national_totals, 'FlowAmount', 'Unit', 'MWh',
        MWh_MJ, 'FlowAmount')
    # drop old unit
    egrid_national_totals.drop('Unit', axis=1, inplace=True)
    validation_result = validate_inventory(flowbyfac, egrid_national_totals,
                                           group_by='flow', tolerance=5.0)
    write_validation_result('eGRID', year, validation_result)


def generate_national_totals(year):
    """Download and process eGRID national totals for validation.

    Resulting file is stored in repository
    """
    log.info(f'Processing eGRID national totals for validation of {year}')
    totals_dict = {'USHTIANT': 'Heat',
                   'USNGENAN': 'Electricity',
                   #'USETHRMO':'Steam', #PLNTYR sheet
                   'USNOXAN': 'Nitrogen oxides',
                   'USSO2AN': 'Sulfur dioxide',
                   'USCO2AN': 'Carbon dioxide',
                   'USCH4AN': 'Methane',
                   'USN2OAN': 'Nitrous oxide',
                   }

    us_totals = extract_eGRID_excel(year, 'US', index='code')
    us_totals = us_totals[list(totals_dict.keys())]
    us_totals.rename(columns=totals_dict, inplace=True)
    us_totals = us_totals.transpose().reset_index()
    us_totals = us_totals.rename(columns={'index': 'FlowName',
                                          0: 'FlowAmount'})

    steam_df = extract_eGRID_excel(year, 'PLNT', index='code')
    steam_total = steam_df['USETHRMO'].sum()
    us_totals = us_totals.append({'FlowName': 'Steam', 'FlowAmount': steam_total},
                                 ignore_index=True)

    flow_compartments = pd.read_csv(eGRID_data_dir + 'eGRID_flow_compartments.csv',
                                    usecols=['FlowName', 'Compartment'])
    us_totals = us_totals.merge(flow_compartments, how='left', on='FlowName')

    us_totals.loc[(us_totals['FlowName'] == 'Carbon dioxide') |
                  (us_totals['FlowName'] == 'Sulfur dioxide') |
                  (us_totals['FlowName'] == 'Nitrogen oxides'),
                  'Unit'] = 'tons'
    us_totals.loc[(us_totals['FlowName'] == 'Methane') |
                  (us_totals['FlowName'] == 'Nitrous oxide'),
                  'Unit'] = 'lbs'
    us_totals.loc[(us_totals['FlowName'] == 'Heat') |
                  (us_totals['FlowName'] == 'Steam'),
                  'Unit'] = 'MMBtu'
    us_totals.loc[(us_totals['FlowName'] == 'Electricity'),
                  'Unit'] = 'MWh'
    log.info(f'saving eGRID_{year}_NationalTotals.csv to {data_dir}')
    us_totals = us_totals[['FlowName', 'Compartment', 'FlowAmount', 'Unit']]
    us_totals.to_csv(data_dir + 'eGRID_' + year + '_NationalTotals.csv', index=False)

    # Update validationSets_Sources.csv
    validation_dict = {'Inventory': 'eGRID',
                       'Version': _config[year]['file_version'],
                       'Year': year,
                       'Name': 'eGRID Data Files',
                       'URL': _config[year]['download_url'],
                       'Criteria': 'Extracted from US Total tab, or for '
                       'steam, summed from PLNT tab',
                       }
    update_validationsets_sources(validation_dict)


def main(**kwargs):

    parser = argparse.ArgumentParser(argument_default = argparse.SUPPRESS)

    parser.add_argument('Option',
                        help = 'What do you want to do:\
                        [A] Download eGRID data\
                        [B] Process and parse eGRID data\
                        [C] National Totals',
                        type = str)

    parser.add_argument('-Y', '--Year', nargs = '+',
                        help = 'What eGRID year you want to retrieve',
                        type = str)

    if len(kwargs) == 0:
        kwargs = vars(parser.parse_args())

    for year in kwargs['Year']:

        if year not in _config:
            log.error(f'Requested eGRID year {year} is not available')
            continue

        if kwargs['Option'] == 'A':
            # download data
            download_eGRID(year)
            generate_metadata(year, datatype='source')

        if kwargs['Option'] == 'B':
            # process and validate data
            generate_eGRID_files(year)
            generate_metadata(year, datatype='inventory')

        if kwargs['Option'] == 'C':
            # download and store national totals
            generate_national_totals(year)


if __name__ == '__main__':
    main()
