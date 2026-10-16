package 'Patrol Vessel Mission System' {
    doc /* Model written from 4 document(s): equipment_inventory.xlsx, software_inventory.csv, cable_run_sheet.csv, interface_control.docx. Every element names the document and the row or line it was read from. */
    part def 'System' {
        doc /* Kind named in: equipment_inventory.xlsx, Equipment, row 2 */
    }
    part def 'Subsystem' {
        doc /* Kind named in: equipment_inventory.xlsx, Equipment, row 3; equipment_inventory.xlsx, Equipment, row 6 */
    }
    part def 'Radar' {
        doc /* Kind named in: equipment_inventory.xlsx, Equipment, row 4 */
    }
    part def 'Processor' {
        doc /* Kind named in: equipment_inventory.xlsx, Equipment, row 5 */
    }
    part def 'Computer' {
        doc /* Kind named in: equipment_inventory.xlsx, Equipment, row 7 */
    }
    part def 'Operator Console' {
        doc /* Kind named in: equipment_inventory.xlsx, Equipment, row 8; equipment_inventory.xlsx, Equipment, row 9 */
    }
    part def 'Network Switch' {
        doc /* Kind named in: equipment_inventory.xlsx, Equipment, row 10 */
    }
    part def 'Power Panel' {
        doc /* Kind named in: equipment_inventory.xlsx, Equipment, row 11 */
    }
    connection def 'Fiber' {
        doc /* Kind named in: cable_run_sheet.csv, row 2 */
        end 'end 1';
        end 'end 2';
    }
    connection def 'Cat6' {
        doc /* Kind named in: cable_run_sheet.csv, row 3; cable_run_sheet.csv, row 4; cable_run_sheet.csv, row 5; cable_run_sheet.csv, row 6; cable_run_sheet.csv, row 8; cable_run_sheet.csv, row 9 */
        end 'end 1';
        end 'end 2';
    }
    connection def 'Power' {
        doc /* Kind named in: cable_run_sheet.csv, row 7 */
        end 'end 1';
        end 'end 2';
    }
    part 'Mission System' : 'System' {
        doc /* Read from: equipment_inventory.xlsx, Equipment, row 2 */
        attribute 'Part number' : ScalarValues::String = "MS-100" {
            doc /* Read from: equipment_inventory.xlsx, Equipment, row 2 */
        }
        part 'Sensor Suite' : 'Subsystem' {
            doc /* Read from: equipment_inventory.xlsx, Equipment, row 3 */
            attribute 'Part number' : ScalarValues::String = "SS-200" {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 3 */
            }
            part 'Surface Search Radar' : 'Radar' {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 4 */
                attribute 'Location' : ScalarValues::String = "Mast" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 4 */
                }
                attribute 'Part number' : ScalarValues::String = "SR-310" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 4 */
                }
                port 'J1' {
                    doc /* Read from: cable_run_sheet.csv, row 2 */
                }
            }
            part 'Radar Processor' : 'Processor' {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 5; software_inventory.csv, row 3 */
                attribute 'Location' : ScalarValues::String = "Equipment Room 2" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 5 */
                }
                attribute 'Part number' : ScalarValues::String = "RP-220" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 5; software_inventory.csv, row 3 */
                }
                attribute 'Software' : ScalarValues::String = "Track Processing" {
                    doc /* Read from: software_inventory.csv, row 3 */
                }
                attribute 'Version' : ScalarValues::String = "3.1.0" {
                    doc /* Read from: software_inventory.csv, row 3 */
                }
                port 'J4' {
                    doc /* Read from: cable_run_sheet.csv, row 2 */
                }
                port 'J7' {
                    doc /* Read from: cable_run_sheet.csv, row 3 */
                }
                port 'PWR' {
                    doc /* Read from: cable_run_sheet.csv, row 7 */
                }
            }
            connection 'W101' : 'Fiber' connect 'Surface Search Radar'.'J1' to 'Radar Processor'.'J4' {
                doc /* Read from: cable_run_sheet.csv, row 2 */
                attribute 'Length (m)' : ScalarValues::Integer = 32 {
                    doc /* Read from: cable_run_sheet.csv, row 2 */
                }
            }
        }
        part 'Combat Management' : 'Subsystem' {
            doc /* Read from: equipment_inventory.xlsx, Equipment, row 6 */
            attribute 'Part number' : ScalarValues::String = "CM-400" {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 6 */
            }
            part 'Mission Computer' : 'Computer' {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 7; software_inventory.csv, row 2 */
                attribute 'Location' : ScalarValues::String = "Equipment Room 2" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 7 */
                }
                attribute 'Part number' : ScalarValues::String {
                    doc /* The sources disagree, so no value is chosen: "MC-410" in equipment_inventory.xlsx, Equipment, row 7; "MC-411" in software_inventory.csv, row 2 */
                }
                attribute 'Software' : ScalarValues::String = "Combat Management Software" {
                    doc /* Read from: software_inventory.csv, row 2 */
                }
                attribute 'Version' : ScalarValues::String = "7.4.2" {
                    doc /* Read from: software_inventory.csv, row 2 */
                }
                port 'J2' {
                    doc /* Read from: cable_run_sheet.csv, row 4 */
                }
            }
            part 'Operator Console A' : 'Operator Console' {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 8; software_inventory.csv, row 4 */
                attribute 'Location' : ScalarValues::String = "Operations Center" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 8 */
                }
                attribute 'Part number' : ScalarValues::String = "OC-4471" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 8; software_inventory.csv, row 4 */
                }
                attribute 'Software' : ScalarValues::String = "Console Display" {
                    doc /* Read from: software_inventory.csv, row 4 */
                }
                attribute 'Version' : ScalarValues::String = "5.0.1" {
                    doc /* Read from: software_inventory.csv, row 4 */
                }
                port 'J3' {
                    doc /* Read from: cable_run_sheet.csv, row 5 */
                }
            }
            part 'Operator Console B' : 'Operator Console' {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 9 */
                attribute 'Location' : ScalarValues::String = "Operations Center" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 9 */
                }
                attribute 'Part number' : ScalarValues::String = "OC-4471" {
                    doc /* Read from: equipment_inventory.xlsx, Equipment, row 9 */
                }
                port 'J3' {
                    doc /* Read from: cable_run_sheet.csv, row 6 */
                }
                port 'J4' {
                    doc /* Read from: cable_run_sheet.csv, row 9 */
                }
            }
            connection 'Display data' connect 'Mission Computer' to 'Operator Console A' {
                doc /* Read from: interface_control.docx, Table 1, row 3 */
                attribute 'Protocol' : ScalarValues::String = "Ethernet" {
                    doc /* Read from: interface_control.docx, Table 1, row 3 */
                }
            }
        }
        part 'Network Switch 2' : 'Network Switch' {
            doc /* Read from: equipment_inventory.xlsx, Equipment, row 10 */
            attribute 'Location' : ScalarValues::String = "Equipment Room 2" {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 10 */
            }
            attribute 'Part number' : ScalarValues::String = "NS-2240" {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 10 */
            }
            port 'P1' {
                doc /* Read from: cable_run_sheet.csv, row 3 */
            }
            port 'P2' {
                doc /* Read from: cable_run_sheet.csv, row 4 */
            }
            port 'P5' {
                doc /* Read from: cable_run_sheet.csv, row 5 */
            }
            port 'P6' {
                doc /* Read from: cable_run_sheet.csv, row 6 */
            }
            port 'P7' {
                doc /* Read from: cable_run_sheet.csv, row 8 */
            }
        }
        part 'Power Panel 2' : 'Power Panel' {
            doc /* Read from: equipment_inventory.xlsx, Equipment, row 11 */
            attribute 'Location' : ScalarValues::String = "Equipment Room 2" {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 11 */
            }
            attribute 'Part number' : ScalarValues::String = "PP-0902" {
                doc /* Read from: equipment_inventory.xlsx, Equipment, row 11 */
            }
            port 'CB4' {
                doc /* Read from: cable_run_sheet.csv, row 7 */
            }
        }
        connection 'W102' : 'Cat6' connect 'Sensor Suite'.'Radar Processor'.'J7' to 'Network Switch 2'.'P1' {
            doc /* Read from: cable_run_sheet.csv, row 3 */
            attribute 'Length (m)' : ScalarValues::Integer = 4 {
                doc /* Read from: cable_run_sheet.csv, row 3 */
            }
        }
        connection 'W103' : 'Cat6' connect 'Combat Management'.'Mission Computer'.'J2' to 'Network Switch 2'.'P2' {
            doc /* Read from: cable_run_sheet.csv, row 4 */
            attribute 'Length (m)' : ScalarValues::Integer = 3 {
                doc /* Read from: cable_run_sheet.csv, row 4 */
            }
        }
        connection 'W104' : 'Cat6' connect 'Combat Management'.'Operator Console A'.'J3' to 'Network Switch 2'.'P5' {
            doc /* Read from: cable_run_sheet.csv, row 5 */
            attribute 'Length (m)' : ScalarValues::Integer = 18 {
                doc /* Read from: cable_run_sheet.csv, row 5 */
            }
        }
        connection 'W105' : 'Cat6' connect 'Combat Management'.'Operator Console B'.'J3' to 'Network Switch 2'.'P6' {
            doc /* Read from: cable_run_sheet.csv, row 6 */
            attribute 'Length (m)' : ScalarValues::Integer = 18 {
                doc /* Read from: cable_run_sheet.csv, row 6 */
            }
        }
        connection 'W106' : 'Power' connect 'Power Panel 2'.'CB4' to 'Sensor Suite'.'Radar Processor'.'PWR' {
            doc /* Read from: cable_run_sheet.csv, row 7 */
            attribute 'Length (m)' : ScalarValues::Integer = 6 {
                doc /* Read from: cable_run_sheet.csv, row 7 */
            }
        }
        connection 'Track data' connect 'Sensor Suite'.'Radar Processor' to 'Combat Management'.'Mission Computer' {
            doc /* Read from: interface_control.docx, Table 1, row 2 */
            attribute 'Protocol' : ScalarValues::String = "Ethernet" {
                doc /* Read from: interface_control.docx, Table 1, row 2 */
            }
        }
    }
    part 'Navigation Radar' {
        doc /* Named only in: cable_run_sheet.csv, row 8. No source describes it in a row of its own */
        port 'J1' {
            doc /* Read from: cable_run_sheet.csv, row 8 */
        }
    }
    connection 'W107' : 'Cat6' connect 'Navigation Radar'.'J1' to 'Mission System'.'Network Switch 2'.'P7' {
        doc /* Read from: cable_run_sheet.csv, row 8 */
        attribute 'Length (m)' : ScalarValues::Integer = 21 {
            doc /* Read from: cable_run_sheet.csv, row 8 */
        }
    }
    dependency from 'Mission System'::'Sensor Suite'::'Surface Search Radar' to 'Mission System'::'Power Panel 2' {
        doc /* Read from: equipment_inventory.xlsx, Equipment, row 4 */
    }
    dependency from 'Mission System'::'Sensor Suite'::'Radar Processor' to 'Mission System'::'Power Panel 2' {
        doc /* Read from: equipment_inventory.xlsx, Equipment, row 5 */
    }
    dependency from 'Mission System'::'Combat Management'::'Mission Computer' to 'Mission System'::'Power Panel 2' {
        doc /* Read from: equipment_inventory.xlsx, Equipment, row 7 */
    }
    dependency from 'Mission System'::'Network Switch 2' to 'Mission System'::'Power Panel 2' {
        doc /* Read from: equipment_inventory.xlsx, Equipment, row 10 */
    }
    comment /* W108 is not drawn: read with 1 end(s), not two. Ends read: Operator Console B port J4 (cable_run_sheet.csv, row 9). */
}
